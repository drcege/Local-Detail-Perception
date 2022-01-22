import random
import tensorflow as tf
import numpy as np
import time
from datetime import timedelta
from PIL import Image
import scipy.io
import os
import argparse
import collections
import math
import sys
sys.path.append('libs')
sys.path.append('tools')

from configs import FLAGS
from data_loader import load_image, load_label, preload_dataset
import adapted_deeplab_model
from segment_densecrf import seg_densecrf
from semantic_visualize import visualize_semantic_segmentation
from edgelist_utils import refine_label_with_edgelist


if 'CUDA_VISIBLE_DEVICES' not in os.environ.keys():
    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
print('CUDA:', os.environ['CUDA_VISIBLE_DEVICES'])


def segment_main(**kwargs):
    mode = kwargs['mode']

    mu = FLAGS.mean

    if FLAGS.ignore_class_bg:
        nSketchClasses = FLAGS.nSketchClasses - 1
        print('Ignore BG;', nSketchClasses, 'classes')
    else:
        nSketchClasses = FLAGS.nSketchClasses
        print('Not Ignore BG;', nSketchClasses, 'classes')

    data_aug = FLAGS.data_aug if mode == 'train' else False

    model = adapted_deeplab_model.DeepLab(num_classes=nSketchClasses,
                                          lrn_rate=FLAGS.learning_rate,
                                          lrn_rate_end=FLAGS.learning_rate_end,
                                          optimizer=FLAGS.optimizer,
                                          upsample_mode=FLAGS.upsample_mode,
                                          data_aug=data_aug,
                                          image_down_scaling=FLAGS.image_down_scaling,
                                          ignore_class_bg=FLAGS.ignore_class_bg,
                                          mode=mode)

    snapshot_saver = tf.train.Saver(max_to_keep=0)

    tfconfig = tf.ConfigProto()
    tfconfig.gpu_options.allow_growth = True
    os.system('sudo nvidia-smi -i %s -c 0' % os.environ['CUDA_VISIBLE_DEVICES'])
    sess = tf.Session(config=tfconfig)
    os.system('sudo nvidia-smi -i %s -c 2' % os.environ['CUDA_VISIBLE_DEVICES'])
    sess.run(tf.global_variables_initializer())

    snapshot_dir = os.path.join(FLAGS.outputs_base_dir, FLAGS.snapshot_folder_name)
    os.makedirs(snapshot_dir, exist_ok=True)
    snapshot_dir = os.path.join(snapshot_dir, kwargs['run_name'])
    os.makedirs(snapshot_dir, exist_ok=(mode != 'train'))

    ckpt = tf.train.get_checkpoint_state(snapshot_dir)
    if not ckpt and not kwargs['ckpt_file']:
        if mode == 'train':
            pretrained_model = FLAGS.resnet_pretrained_model_path
            load_var = {var.op.name: var for var in tf.global_variables()
                        if var.op.name.startswith('ResNet')
                        and 'factor' not in var.op.name
                        and 'Adam' not in var.op.name
                        and 'beta1_power' not in var.op.name
                        and 'beta2_power' not in var.op.name
                        and 'fc_final_sketch46' not in var.op.name
                        and 'global_step' not in var.op.name  # count from 0
                        }
            snapshot_loader = tf.train.Saver(load_var)
            print('Firstly training, loaded', pretrained_model)
            snapshot_loader.restore(sess, pretrained_model)
        else:
            raise Exception("No pre-trained model for %s" % mode)
    else:
        load_var = {var.op.name: var for var in tf.global_variables()
                    if var.op.name.startswith('ResNet')
                    and 'global_step' not in var.op.name  # count from 0
                    }

        snapshot_loader = tf.train.Saver(load_var)
        if kwargs['ckpt_file']:
            ckpt_file = kwargs['ckpt_file']
        else:
            ckpt_file = ckpt.model_checkpoint_path
        print('Trained model found, loaded', ckpt_file)
        snapshot_loader.restore(sess, ckpt_file)

    if mode == 'train':
        log_dir = os.path.join(FLAGS.outputs_base_dir, FLAGS.log_folder_name)
        os.makedirs(log_dir, exist_ok=True)
        log_dir = os.path.join(log_dir, kwargs['run_name'])
        os.makedirs(log_dir)

        snapshot_file = os.path.join(snapshot_dir, 'iter_%d.tfmodel')

        summary_op = tf.summary.merge_all()
        summary_writer = tf.summary.FileWriter(log_dir, graph=sess.graph)

        duration_time_n_step = 0

        print('Loading dataset...')
        ims, gts = preload_dataset(FLAGS.data_base_dir, mode, FLAGS.nTrainImgs, mu, 'class', FLAGS.ignore_class_bg)
        print('Dataset loaded!')
        for n_iter in range(FLAGS.max_iteration):
            start_time = time.time()

            print('\n#' + str(n_iter))

            ## select image index
            image_idx = random.randint(0, FLAGS.nTrainImgs-1)

            im = ims[image_idx]
            label = gts[image_idx]
            print("Ori shape", im.shape)

            feed_dict = {model.images: im, model.labels: label}
            _, learning_rate_, global_step, cost, pred, pred_label = \
                sess.run([model.train_step,
                          model.learning_rate,
                          model.global_step,
                          model.cost,
                          model.pred,
                          model.pred_label],
                         feed_dict=feed_dict)
            print('pred.shape', pred.shape)  # (1, H_scale, W_scale, nClasses)

            print('learning_rate_', learning_rate_)
            # print('global_step', global_step)
            print('cost', cost)

            ## display left time
            duration_time = time.time() - start_time
            duration_time_n_step += duration_time
            if n_iter % FLAGS.count_left_time_freq == 0 and n_iter != 0:
                left_step = FLAGS.max_iteration - n_iter
                left_sec = left_step / FLAGS.count_left_time_freq * duration_time_n_step
                print("Duration_time_%d_step: %s. Left time: %s" % (
                    FLAGS.count_left_time_freq,
                    str(timedelta(seconds=duration_time_n_step)),
                    str(timedelta(seconds=left_sec))))
                duration_time_n_step = 0

            ## summary
            if n_iter % FLAGS.summary_write_freq == 0 and n_iter != 0:
                summary_str = sess.run(summary_op, feed_dict=feed_dict)
                summary_writer.add_summary(summary_str, n_iter)
                summary_writer.flush()

            ## save model
            if (n_iter + 1) % FLAGS.save_model_freq == 0 or (n_iter + 1) >= FLAGS.max_iteration:
                snapshot_saver.save(sess, snapshot_file % (n_iter + 1))
                print('model saved to ' + snapshot_file % (n_iter + 1))

        print('Training done.')

    elif mode == 'val' or mode == 'test':

        def fast_hist(a, b, n):
            """
            :param a: gt
            :param b: pred
            """
            k = (a >= 0) & (a < n)
            return np.bincount(n * a[k].astype(int) + b[k], minlength=n ** 2).reshape(n, n)

        use_dcrf = kwargs['use_dcrf']
        use_edgelist = kwargs['use_edgelist']
        eval_base_dir = os.path.join(FLAGS.outputs_base_dir, 'eval_results')
        os.makedirs(eval_base_dir, exist_ok=True)

        nImgs = FLAGS.nTestImgs if mode == 'test' else FLAGS.nValImgs
        colorMap = scipy.io.loadmat(os.path.join(FLAGS.data_base_dir, 'colorMap.mat'))['colorMap']
        outstr = mode + ' mode\n'
        cat_max_len = 16

        hist = np.zeros((FLAGS.nSketchClasses, FLAGS.nSketchClasses))

        for imgIndex in range(1, nImgs + 1):
            ## load images
            image_name = 'L0_sample' + str(imgIndex) + '.png'  # e.g. L0_sample5564.png
            image_path = os.path.join(FLAGS.data_base_dir, mode, 'DRAWING_GT', image_name)
            test_image = load_image(image_path, mu)  # shape = [1, H, W, 3]

            ## load gt_label
            label_name = 'sample_' + str(imgIndex) + '_class.mat'  # e.g. sample_1_class.mat
            label_path = os.path.join(FLAGS.data_base_dir, mode, 'CLASS_GT', label_name)
            gt_label = np.squeeze(load_label(label_path))  # [1, H, W] -> [1, H, W]

            print('#' + str(imgIndex) + '/' + str(nImgs) + ': ' + image_path)

            feed_dict = {model.images: test_image, model.labels: 0}
            pred, pred_label_no_crf = sess.run([model.pred, model.pred_label], feed_dict=feed_dict)
            if FLAGS.ignore_class_bg:
                pred_label_no_crf = pred_label_no_crf + 1  # [1, 46]

            # print('@ pred.shape ', pred.shape)  # (1, H, W, nSketchClasses)
            # print(pred_label_no_crf.shape)  # shape = [1, H, W, 1]

            if use_dcrf:
                prob_arr = np.squeeze(pred)
                prob_arr = prob_arr.transpose((2, 0, 1))  # shape = (nSketchClasses, H, W)
                d_image = np.array(np.squeeze(test_image), dtype=np.uint8)  # shape = (H, W, 3)
                pred_label = seg_densecrf(prob_arr, d_image, nSketchClasses)  # shape=[H, W]
                if FLAGS.ignore_class_bg:
                    pred_label = pred_label + 1  # [1, 46]
            else:
                pred_label = np.squeeze(pred_label_no_crf)  # [H, W], [1,46]

            # ignore background pixel prediction (was random)
            # must before edgelist
            pred_label[gt_label == 0] = 0
            if use_edgelist:
                pred_label = \
                refine_label_with_edgelist(imgIndex, mode, \
                                           FLAGS.data_base_dir,
                                           pred_label.copy())

            hist += fast_hist(gt_label.flatten(),
                              pred_label.flatten(),
                              FLAGS.nSketchClasses)

            if imgIndex == nImgs:
                ## ignore bg pixel with value 0
                if FLAGS.ignore_class_bg:
                    hist = hist[1:, 1:]

                log_str = '\nRound {}, CRF({}), edgelist({})'.format(imgIndex, use_dcrf, use_edgelist)
                print(log_str)
                outstr += log_str + '\n'

                # overall accuracy
                acc = np.diag(hist).sum() / hist.sum()
                print('>>> overall accuracy', acc)
                outstr += '>>> overall accuracy ' + str(acc) + '\n'

                # mAcc
                acc = np.diag(hist) / hist.sum(1)
                acc = np.nan_to_num(acc)
                mean_acc = np.nanmean(acc)
                print('>>> mean accuracy', mean_acc)
                outstr += '>>> mean accuracy ' + str(mean_acc) + '\n'

                # mIoU
                iou = np.diag(hist) / (hist.sum(1) + hist.sum(0) - np.diag(hist))
                iou = np.nan_to_num(iou)
                mean_iou = np.nanmean(iou)
                print('>>> mean IoU', mean_iou)
                outstr += '>>> mean IoU ' + str(mean_iou) + '\n'

                # FWIoU
                freq = hist.sum(1) / hist.sum()
                fw_iou = (freq[freq > 0] * iou[freq > 0]).sum()
                print('>>> freq weighted IoU', fw_iou)
                print('\n')
                outstr += '>>> freq weighted IoU ' + str(fw_iou) + '\n'

                # IoU of each class
                print('>>> IoU of each class')
                outstr += '\n>>> IoU of each class' + '\n'
                for classIdx in range(nSketchClasses):
                    if FLAGS.ignore_class_bg:
                        cat_name = colorMap[classIdx][0][0]
                    else:
                        if classIdx == 0:
                            cat_name = 'background'
                        else:
                            cat_name = colorMap[classIdx - 1][0][0]

                    singlestr = '    >>> '
                    cat_len = len(cat_name)
                    pad = ''
                    for ipad in range(cat_max_len - cat_len):
                        pad += ' '
                    singlestr += cat_name + pad + str(iou[classIdx])
                    print(singlestr)
                    outstr += singlestr + '\n'

        # write validation result to txt
        write_path = os.path.join(eval_base_dir, mode + '_results.txt')
        fp = open(write_path, 'a')
        fp.write(outstr)
        fp.close()

    else:  # 'inference'
        inference_ids = kwargs['inference_id']
        assert isinstance(inference_ids, collections.Sequence)
        inference_dataset = kwargs['inference_dataset']
        black_bg = kwargs['black_bg']
        use_dcrf = kwargs['use_dcrf']
        use_edgelist = kwargs['use_edgelist']

        colorMap = scipy.io.loadmat(os.path.join(FLAGS.data_base_dir, 'colorMap.mat'))['colorMap']

        infer_result_base_dir = os.path.join(FLAGS.outputs_base_dir, 'inference_results', kwargs['run_name'], inference_dataset)
        os.makedirs(infer_result_base_dir, exist_ok=True)

        for img_count, img_id in enumerate(inference_ids):
            image_name = 'L0_sample' + str(img_id) + '.png'  # e.g. L0_sample5564.png
            image_path = os.path.join(FLAGS.data_base_dir, inference_dataset, 'DRAWING_GT', image_name)
            infer_image, infer_image_raw = load_image(image_path, mu, return_raw=True)  # shape = [1, H, W, 3] / [H, W, 3]

            print('\n#' + str(img_count + 1) + '/' + str(len(inference_ids)) + ': ' + image_name)

            feed_dict = {model.images: infer_image, model.labels: 0}
            pred, pred_label_no_crf, feat_visual \
                = sess.run([model.pred, model.pred_label, model.feat_visual], feed_dict=feed_dict)

            print('@ pred.shape ', pred.shape)  # (1, H, W, nSketchClasses)
            print('@ pred_label_no_crf.shape ', pred_label_no_crf.shape)  # shape = [1, H, W, 1], contains [0, nClasses)
            # print('@ feat_visual.shape ', feat_visual.shape)  # shape = (1, 94, 94, 512)

            infer_output_name = 'deeplab_output'
            if use_dcrf:
                infer_output_name += '_crf'
                prob_arr = np.squeeze(pred)
                prob_arr = prob_arr.transpose((2, 0, 1))  # shape = (nSketchClasses, H, W)
                d_image = np.array(np.squeeze(infer_image), dtype=np.uint8)  # shape = (H, W, 3)
                pred_label = seg_densecrf(prob_arr, d_image, nSketchClasses)  # shape=[H, W], contains [0-46/47]
                if FLAGS.ignore_class_bg:
                    pred_label += 1
            else:
                pred_label = np.squeeze(pred_label_no_crf)

            pred_label[infer_image_raw[:, :, 0] != 0] = 0  # [H, W]
            if use_edgelist:
                infer_output_name += '_edgelist'
                pred_label = \
                refine_label_with_edgelist(img_id, inference_dataset, \
                                           FLAGS.data_base_dir,
                                           pred_label.copy())

            save_base_dir = os.path.join(infer_result_base_dir, infer_output_name)
            os.makedirs(save_base_dir, exist_ok=True)

            save_path = os.path.join(save_base_dir, 'sem_result_' + str(img_id) + '.png')
            visualize_semantic_segmentation(pred_label, colorMap, black_bg=black_bg, save_path=save_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', '-md', type=str, choices=['train', 'val', 'test', 'inference'],
                        default='train', help="choose a running mode")
    parser.add_argument('--infer_dataset', '-infd', type=str, choices=['val', 'test'],
                        default='val', help="choose a dataset for inference")
    parser.add_argument('--image_id', '-id', type=int, default=-1, help="choose an image for inference", nargs='+')
    parser.add_argument('--black_bg', '-bl', type=int, choices=[0, 1],
                        default=0, help="use black or white background for inference")
    parser.add_argument('--dcrf', '-crf', type=int, choices=[0, 1],
                        default=1, help="use dense crf or not")
    parser.add_argument('--edgelist', '-el', type=int, choices=[0, 1],
                        default=0, help="use edgelist or not")
    parser.add_argument('--run_name', '-rn', type=str, help="run name")
    parser.add_argument('--ckpt_file', '-cf', type=str, 
                        default=None, help="checkpoint file to restore (without suffix)")

    args = parser.parse_args()

    if args.mode == 'inference' and args.image_id == -1:
        z = input('If inference all? [y/n]: ')
        if z.lower() == 'y':
            args.image_id = range(1, FLAGS.nTestImgs + 1)
        else:
            raise Exception("An image should be chosen for inference.")

    run_params = {
        "mode": args.mode,
        "inference_id": args.image_id,
        "inference_dataset": args.infer_dataset,
        "black_bg": args.black_bg,
        "use_dcrf": args.dcrf,
        "use_edgelist": args.edgelist,
        "run_name": args.run_name,
        "ckpt_file": args.ckpt_file
    }

    segment_main(**run_params)
