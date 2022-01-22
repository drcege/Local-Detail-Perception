%% set the dataset type here, ['test', 'val']
dataset_type = 'test';

%% 
data_base_dir = '../../datasets/SketchyScene/SketchyScene-7k/';

if strcmp(dataset_type, 'test')
    nImgs = 1113;
else
    nImgs = 535;
end

split_save_base_dir = [data_base_dir, dataset_type, '/edgelist/'];
mkdir(split_save_base_dir);

for n = 1:nImgs
    %n
    img_path = [data_base_dir, dataset_type, '/DRAWING_GT/'];
    img_path = strcat(img_path, sprintf( 'L0_sample%d.png', n));
    im = imread(img_path);
    im = im(:, :, 1);
    %edgeim = 1 - im;
    edgeim = ~im;
    
    [edgelist, labelededgeim] = edgelink(edgeim, 10);
    
    save_path = strcat(split_save_base_dir, sprintf('edgelist_%d.mat', n));
    save(save_path, 'labelededgeim');
end
