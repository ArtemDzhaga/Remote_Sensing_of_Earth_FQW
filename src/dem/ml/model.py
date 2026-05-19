# -*- coding: utf-8 -*-
"""Архитектуры сетей для DEM-коррекции."""

from __future__ import annotations


def build_model(
    *,
    in_channels: int = 5,
    classes: int = 1,
    encoder_name: str = "resnet18",
    encoder_weights: str | None = None,
    prefer_smp: bool = True,
    require_smp: bool = False,
):
    """Собрать модель.

    Если установлен `segmentation_models_pytorch`, используется U-Net с заданным
    encoder. Иначе возвращается компактная CNN, достаточная для smoke-прогона.
    """

    import torch
    from torch import nn

    if prefer_smp:
        try:
            import segmentation_models_pytorch as smp

            return smp.Unet(
                encoder_name=encoder_name,
                encoder_weights=encoder_weights,
                in_channels=in_channels,
                classes=classes,
            )
        except ImportError:
            if require_smp:
                raise RuntimeError(
                    "Для ResNet-U-Net нужен пакет segmentation_models_pytorch. "
                    "Установи ML-зависимости проекта и повтори запуск."
                ) from None

    return nn.Sequential(
        nn.Conv2d(in_channels, 32, kernel_size=3, padding=1),
        nn.ReLU(inplace=True),
        nn.Conv2d(32, 32, kernel_size=3, padding=1),
        nn.ReLU(inplace=True),
        nn.Conv2d(32, classes, kernel_size=1),
    )


def default_device() -> str:
    """Подобрать устройство: Apple Silicon MPS → CUDA → CPU."""

    import torch

    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"
