import os
from PIL import Image
import numpy as np
import scipy.io


def printLabelArray(label):
    for i in range(label.shape[0]):
        outstr = ''
        for j in range(label.shape[1]):
            outstr += str(label[i][j]) + ' '
        print(outstr)


def load_image(imname, mu, return_raw=False):
    img = Image.open(imname).convert("RGB")
    im = np.array(img, dtype=np.float32)  # shape = [H, W, 3]
    im = im[:, :, ::-1]  # rgb -> bgr
    im -= mu  # subtract mean
    im = np.expand_dims(im, axis=0)  # shape = [1, H, W, 3]

    if return_raw:
        im_raw = np.array(img, dtype=np.uint8)  # shape = [H, W, 3]
        return im, im_raw
    else:
        return im


def load_label(label_path_):
    label = scipy.io.loadmat(label_path_)['CLASS_GT']
    label = np.array(label, dtype=np.uint8)  # shape = [H, W]
    label = label[np.newaxis, ...]  # shape = [1, H, W]
    return label


def preload_dataset(data_dir, mode, n_imgs, mu, task='class', ignore_class_bg=False):
    assert task in ('class', 'instance')

    ims = []
    gts = []

    for image_idx in range(1, n_imgs+1):
        ## load images
        image_name = 'L0_sample' + str(image_idx) + '.png'  # e.g. L0_sample5564.png
        image_path = os.path.join(data_dir, mode, 'DRAWING_GT', image_name)
        ims.append(load_image(image_path, mu))  # shape = [1, H, W, 3]

        ## load label
        label_name = 'sample_' + str(image_idx) + '_' + task + '.mat'  # e.g. sample_1_class.mat
        gt_folder = task.upper() + '_GT'
        label_path = os.path.join(data_dir, mode, gt_folder, label_name)
        label = load_label(label_path)  # shape = [1, H, W], [0, 46]

        if ignore_class_bg:
            label = label - 1  # [-1, 45]
            label[label == -1] = 255  # [0-45, 255]

        gts.append(label)
            
    return (ims, gts)
