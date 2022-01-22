# Exploring Local Detail Perception for Scene Sketch Semantic Segmentation

Code release for ["Exploring Local Detail Perception for Scene Sketch Semantic Segmentation"](https://doi.org/10.1109/TIP.2022.3142511) (IEEE TIP)

## Requirements

- Create a conda environment from the `environment.yml` file:
```bash
conda env create -f environment.yml
```

- Activate the environment: 

```bash
conda activate LDP
```

## Preparations

- Get the code:

```bash
git clone https://github.com/drcege/Local-Detail-Perception && cd Local-Detail-Perception
```

- Download datasets and place them under the `datasets` directory following its instructions.

- Generate ImageNet pre-trained "ResNet-101" model in TensorFlow version for initial training and place it under the `resnet_pretrained_model` directory. This can be obtained following the instructions in [chenxi116/TF-resnet](https://github.com/chenxi116/TF-resnet#example-usage). For convenience, the converted model can be downloaded from [here](https://drive.google.com/drive/folders/11sI3IARgAKTf4rut1isQgTOdGKFeyZ1c?usp=sharing).

## Training

```bash
python3 segment_main.py --mode=train --run_name=LDP 
```

## Evaluation

```
python3 segment_main.py --mode=test --run_name=LDP
```

## Credits

- The ResNet-101 model pre-trained on ImageNet in TensorFlow is created by [chenxi116](https://github.com/chenxi116/TF-resnet)
- The code for the DeepLab model is authored by [Tensorflow authors](https://github.com/tensorflow/models/blob/master/research/resnet/resnet_model.py) and [chenxi116](https://github.com/chenxi116/TF-deeplab)
- The repository is developed based on [SketchyScene](https://github.com/SketchyScene/SketchyScene)

