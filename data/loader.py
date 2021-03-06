""" Object detection loader/collate

Hacked together by Ross Wightman
"""
import torch.utils.data
from .transforms import *


MAX_NUM_INSTANCES = 100


def fast_collate(batch):
    batch_size = len(batch)

    # FIXME this needs to be more robust
    target = dict()
    for k, v in batch[0][1].items():
        if isinstance(v, np.ndarray):
            target_shape = (batch_size, MAX_NUM_INSTANCES)
            if len(v.shape) > 1:
                target_shape = target_shape + v.shape[1:]
            target_dtype = torch.float32
        else:
            target_shape = batch_size,
            target_dtype = torch.float32 if isinstance(v, float) else torch.int64
        target[k] = torch.zeros(target_shape, dtype=target_dtype)

    tensor = torch.zeros((batch_size, *batch[0][0].shape), dtype=torch.uint8)
    for i in range(batch_size):
        tensor[i] += torch.from_numpy(batch[i][0])
        for tk, tv in batch[i][1].items():
            if isinstance(tv, np.ndarray) and len(tv.shape):
                target[tk][i, 0:tv.shape[0]] = torch.from_numpy(tv)
            else:
                target[tk][i] = tv

    return tensor, target


class PrefetchLoader:

    def __init__(self,
            loader,
            mean=IMAGENET_DEFAULT_MEAN,
            std=IMAGENET_DEFAULT_STD,
            fp16=False):
        self.loader = loader
        self.mean = torch.tensor([x * 255 for x in mean]).cuda().view(1, 3, 1, 1)
        self.std = torch.tensor([x * 255 for x in std]).cuda().view(1, 3, 1, 1)

    def __iter__(self):
        stream = torch.cuda.Stream()
        first = True

        for next_input, next_target in self.loader:
            with torch.cuda.stream(stream):
                next_input = next_input.cuda(non_blocking=True)
                next_input = next_input.float().sub_(self.mean).div_(self.std)
                next_target = {k: v.cuda(non_blocking=True) for k, v in next_target.items()}

            if not first:
                yield input, target
            else:
                first = False

            torch.cuda.current_stream().wait_stream(stream)
            input = next_input
            target = next_target

        yield input, target

    def __len__(self):
        return len(self.loader)

    @property
    def sampler(self):
        return self.loader.sampler


def create_loader(
        dataset,
        input_size,
        batch_size,
        is_training=False,
        use_prefetcher=True,
        interpolation='bilinear',
        mean=IMAGENET_DEFAULT_MEAN,
        std=IMAGENET_DEFAULT_STD,
        num_workers=1,
        pin_mem=False,
):
    if isinstance(input_size, tuple):
        img_size = input_size[-2:]
    else:
        img_size = input_size

    if is_training:
        assert False, 'work in progress'
    else:
        transform = transforms_coco_eval(
            img_size,
            interpolation=interpolation,
            use_prefetcher=use_prefetcher,
            mean=mean,
            std=std)

    dataset.transform = transform

    loader = torch.utils.data.DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=pin_mem,
        collate_fn=fast_collate if use_prefetcher else torch.utils.data.dataloader.default_collate,
    )
    if use_prefetcher:
        loader = PrefetchLoader(loader, mean=mean, std=std)

    return loader
