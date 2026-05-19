# -*- coding: utf-8 -*-
"""Минимальный train loop для MVP-модели DEM-коррекции."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

from dem.io.layout import outputs_root, resolve_out_dir
from dem.ml.dataset import DemPatchDataset
from dem.ml.loss import masked_mae, slope_aware_mae
from dem.ml.model import build_model, default_device


def _metrics(pred, target, valid_mask, *, data_range: float) -> dict[str, float]:
    import torch

    err = pred - target
    if valid_mask is not None:
        err = err[valid_mask]
    if err.numel() == 0:
        return {"mae": float("nan"), "rmse": float("nan"), "psnr": float("nan")}
    mae = torch.mean(torch.abs(err)).item()
    rmse = torch.sqrt(torch.mean(err**2)).item()
    psnr = 20.0 * math.log10(data_range / max(rmse, 1e-12)) if data_range > 0 else float("nan")
    return {"mae": mae, "rmse": rmse, "psnr": psnr}


def _clean_batch(batch, device: str):
    import torch

    x = batch["x"].to(device=device, dtype=torch.float32)
    y = batch["y"].to(device=device, dtype=torch.float32)
    valid = torch.isfinite(y)
    x = torch.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    y = torch.nan_to_num(y, nan=0.0, posinf=0.0, neginf=0.0)
    return x, y, valid


def _make_loaders(args: argparse.Namespace):
    import torch
    from torch.utils.data import DataLoader, random_split

    root = Path(args.data_dir)
    train_dir = root / "train"
    val_dir = root / "val"

    if train_dir.is_dir():
        train_ds = DemPatchDataset(train_dir, augment=True)
        val_ds = DemPatchDataset(val_dir, augment=False) if val_dir.is_dir() else None
    else:
        full = DemPatchDataset(root, augment=False)
        val_len = max(1, int(len(full) * args.val_fraction)) if len(full) > 1 else 0
        train_len = len(full) - val_len
        gen = torch.Generator().manual_seed(args.seed)
        train_ds, val_ds = random_split(full, [train_len, val_len], generator=gen) if val_len else (full, None)
        if hasattr(train_ds, "dataset"):
            train_ds.dataset.augment = True

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=args.num_workers)
    val_loader = (
        DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=args.num_workers) if val_ds else None
    )
    return train_loader, val_loader


def train(args: argparse.Namespace) -> Path:
    import numpy as np
    import torch

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    out_dir = resolve_out_dir(args.out_dir, lambda: outputs_root() / "models" / "dem_mvp")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "train_config.json").write_text(
        json.dumps(vars(args), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    train_loader, val_loader = _make_loaders(args)
    first = next(iter(train_loader))
    in_channels = int(first["x"].shape[1])
    device = args.device if args.device != "auto" else default_device()

    encoder_weights = args.encoder_weights if args.encoder_weights else None
    model = build_model(
        in_channels=in_channels,
        classes=1,
        encoder_name=args.encoder_name,
        encoder_weights=encoder_weights,
        prefer_smp=not args.no_smp,
        require_smp=args.require_smp,
    ).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        opt,
        max_lr=args.lr,
        epochs=args.epochs,
        steps_per_epoch=max(1, len(train_loader)),
    )

    history: list[dict] = []
    best_rmse = float("inf")
    best_metrics: dict | None = None
    best_path = out_dir / "best.pt"

    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss = 0.0
        train_n = 0
        for batch in train_loader:
            x, y, valid = _clean_batch(batch, device)
            pred = model(x)
            if 0 <= args.slope_channel < x.shape[1]:
                slope = x[:, args.slope_channel : args.slope_channel + 1]
                loss = slope_aware_mae(pred, y, slope, alpha=args.slope_alpha, valid_mask=valid)
            else:
                loss = masked_mae(pred, y, valid)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            scheduler.step()
            train_loss += float(loss.item())
            train_n += 1

        row = {"epoch": epoch, "train_loss": train_loss / max(1, train_n)}

        if val_loader is not None:
            model.eval()
            vals: list[dict[str, float]] = []
            with torch.no_grad():
                for batch in val_loader:
                    x, y, valid = _clean_batch(batch, device)
                    vals.append(_metrics(model(x), y, valid, data_range=args.psnr_range))
            for key in ("mae", "rmse", "psnr"):
                row[f"val_{key}"] = sum(v[key] for v in vals) / max(1, len(vals))

            if row["val_rmse"] < best_rmse:
                best_rmse = row["val_rmse"]
                best_metrics = dict(row)
                torch.save(
                    {
                        "model": model.state_dict(),
                        "epoch": epoch,
                        "in_channels": in_channels,
                        "encoder_name": args.encoder_name,
                        "encoder_weights": encoder_weights,
                        "prefer_smp": not args.no_smp,
                        "metrics": row,
                    },
                    best_path,
                )
        else:
            best_metrics = dict(row)
            torch.save(
                {
                    "model": model.state_dict(),
                    "epoch": epoch,
                    "in_channels": in_channels,
                    "encoder_name": args.encoder_name,
                    "encoder_weights": encoder_weights,
                    "prefer_smp": not args.no_smp,
                    "metrics": row,
                },
                best_path,
            )

        history.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    (out_dir / "history.json").write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    if best_metrics is not None:
        (out_dir / "best_metrics.json").write_text(
            json.dumps(
                {
                    "checkpoint": str(best_path),
                    "metrics": best_metrics,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    _write_learning_curve(history, out_dir / "learning_curves.png")
    print(f"best: {best_path}")
    return best_path


def _write_learning_curve(history: list[dict], out_png: Path) -> None:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return

    epochs = [h["epoch"] for h in history]
    plt.figure(figsize=(7, 4))
    plt.plot(epochs, [h["train_loss"] for h in history], label="train_loss")
    if "val_rmse" in history[-1]:
        plt.plot(epochs, [h["val_rmse"] for h in history], label="val_rmse")
    plt.xlabel("epoch")
    plt.grid(True, alpha=0.3)
    plt.legend()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_png, dpi=150)
    plt.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Обучить MVP DEM-модель на .npz патчах.")
    p.add_argument("--data-dir", required=True, help="Папка с .npz или train/val подпапками.")
    p.add_argument("--out-dir", default="", help="Пусто = outputs/<дата>/models/dem_mvp")
    p.add_argument("--epochs", type=int, default=10)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--weight-decay", type=float, default=1e-4)
    p.add_argument("--val-fraction", type=float, default=0.2)
    p.add_argument("--num-workers", type=int, default=0)
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "mps", "cuda"])
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--encoder-name", default="resnet18", help="Encoder для U-Net из segmentation_models_pytorch.")
    p.add_argument(
        "--encoder-weights",
        default="",
        help="Веса encoder; пусто = обучение с нуля без загрузки из сети, например imagenet = pretrained.",
    )
    p.add_argument("--slope-channel", type=int, default=-1, help="Индекс slope-канала для slope-aware loss; -1 = MAE.")
    p.add_argument("--slope-alpha", type=float, default=1.0)
    p.add_argument("--psnr-range", type=float, default=1000.0, help="Диапазон высот для PSNR, в метрах.")
    p.add_argument("--no-smp", action="store_true", help="Не использовать segmentation_models_pytorch, даже если установлен.")
    p.add_argument("--require-smp", action="store_true", help="Упасть с ошибкой, если segmentation_models_pytorch недоступен.")
    return p


def main() -> None:
    train(build_parser().parse_args())


if __name__ == "__main__":
    main()
