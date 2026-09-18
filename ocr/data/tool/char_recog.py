"""
run single image characters recognition
"""
import numpy as np
import os.path as osp
import torch.nn as nn
import torch, cv2, math, os
import torch.nn.functional as F


class Charnet(nn.Module):
    def __init__(self, num_classes=27536):
        super(Charnet, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(1, 96, 7, stride=1, padding=3),
            nn.BatchNorm2d(96),
            nn.PReLU(),
            nn.MaxPool2d(2, 2),

            nn.Conv2d(96, 128, 3, stride=1, padding=1),
            nn.BatchNorm2d(128),
            nn.PReLU(),
            nn.MaxPool2d(2, 2),

            nn.Conv2d(128, 160, 3, stride=1, padding=1),
            nn.BatchNorm2d(160),
            nn.PReLU(),
            nn.MaxPool2d(2, 2),

            nn.Conv2d(160, 256, 3, stride=1, padding=1),
            nn.BatchNorm2d(256),
            nn.PReLU(),
            nn.Conv2d(256, 256, 3, stride=1, padding=1),
            nn.BatchNorm2d(256),
            nn.PReLU(),
            nn.MaxPool2d(2, 2),

            nn.Conv2d(256, 384, 3, stride=1, padding=1),
            nn.BatchNorm2d(384),
            nn.PReLU(),
            nn.Conv2d(384, 384, 3, stride=1, padding=1),
            nn.BatchNorm2d(384),
            nn.PReLU(),
            nn.MaxPool2d(2, 2),
        )
        self.fc = nn.Sequential(
            nn.Linear(384 * 3 * 3, 1024),
            nn.BatchNorm1d(1024),
            nn.PReLU(),
            nn.Dropout(p=0.5),
            nn.Linear(1024, num_classes),
        )

    def forward(self, x):
        out = self.conv(x)
        out = out.view(out.size(0), -1)
        out = self.fc[0](out)
        out = self.fc[1](out)
        out = self.fc[2](out)
        return out


class CharRecog(object):
    def __init__(self, model_path, device, recog_thresh, num_classes):
        self.device = device
        self.model = torch.nn.DataParallel(Charnet(num_classes=num_classes)).to(device)
        self.char_model_init(model_path)
        self.model.eval()

        self.thresh = recog_thresh

    def char_model_init(self, model_path):
        if torch.cuda.is_available():
            checkpoint = torch.load(model_path, map_location='cuda:0')
        else:
            checkpoint = torch.load(model_path, map_location='cpu')
        self.model.load_state_dict(checkpoint['state_dict'])

    def single_char_recog(self, img):
        pred_output = []
        pred_prob = []

        crop = cv2.resize(img, (96, 96), interpolation=cv2.INTER_CUBIC)
        # normalize
        crop = crop / 127.5 - 1
        input_ = torch.from_numpy(crop[np.newaxis, np.newaxis, :, :]).type(torch.FloatTensor).to(self.device)
        output = self.model(input_)
        return output.tolist()[0]

    def batch_char_recog(self, root):
        bs = 32
        all_out = []
        imgs_crop = []
        li_name = []
        for i in os.listdir(root):
            li_name.append(i)
            crop = cv2.imread(root + i, 0)
            crop = cv2.resize(crop, (96, 96), interpolation=cv2.INTER_CUBIC)
            imgs_crop.append(crop)
        imgs_crop = np.array(imgs_crop)
        # coors = np.array(coors)

        # normalize
        imgs_crop = imgs_crop / 127.5
        imgs_crop = imgs_crop - 1
        num_batches = math.ceil(len(imgs_crop) / bs)
        for idx in range(num_batches):
            if (idx + 1) * bs <= imgs_crop.shape[0]:
                batch_input = torch.tensor(imgs_crop[idx * bs:(idx + 1) * bs][:, np.newaxis, :, :]).type(
                    torch.FloatTensor).to(self.device)
            else:
                batch_input = torch.tensor(imgs_crop[idx * bs:][:, np.newaxis, :, :]).type(torch.FloatTensor).to(
                    self.device)

            output = self.model(batch_input)
            for v in output:
                all_out.append(v.tolist())
        return all_out, li_name

    def batch_char_recog2(self, imgs_crop):
        bs = 32
        all_out = []
        imgs_crop = np.array(imgs_crop)
        # coors = np.array(coors)

        # normalize
        imgs_crop = imgs_crop / 127.5
        imgs_crop = imgs_crop - 1
        num_batches = math.ceil(len(imgs_crop) / bs)
        for idx in range(num_batches):
            if (idx + 1) * bs <= imgs_crop.shape[0]:
                batch_input = torch.tensor(imgs_crop[idx * bs:(idx + 1) * bs][:, np.newaxis, :, :]).type(
                    torch.FloatTensor).to(self.device)
            else:
                batch_input = torch.tensor(imgs_crop[idx * bs:][:, np.newaxis, :, :]).type(torch.FloatTensor).to(
                    self.device)

            output = self.model(batch_input)
            for v in output:
                all_out.append(v.tolist())
        return all_out
