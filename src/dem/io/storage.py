# -*- coding: utf-8 -*-
"""
Абстракция хранилища: локальная ФС (по умолчанию) и задел под S3-совместимые бакеты.

Фактические пути вывода по-прежнему задаются в dem.io.layout; здесь — интерфейс для
будущей загрузки вещей на объектное хранилище без привязки к провайдеру.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    """Минимальный контракт: записать файл как объект по ключу."""

    def put_file(self, local_path: Path, key: str) -> str:
        """Возвращает URI или ключ загруженного объекта."""
        ...


class LocalFSStorage:
    """«Хранилище» как копирование в каталог внутри репозитория (без облака)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def put_file(self, local_path: Path, key: str) -> str:
        dest = self.root / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(Path(local_path).read_bytes())
        return dest.as_posix()


class ObjectStorageStub:
    """Заготовка под boto3/minio: реализуйте put_file при необходимости."""

    def __init__(self, bucket: str, prefix: str = "") -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def put_file(self, local_path: Path, key: str) -> str:
        raise NotImplementedError(
            "Подключите boto3 и загрузку в бакет; ключ: "
            f"s3://{self.bucket}/{self.prefix}/{key}"
        )
