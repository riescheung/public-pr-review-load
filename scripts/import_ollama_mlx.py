#!/usr/bin/env python3
"""Repackage installed Ollama MLX tensors without downloads or dequantization."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct

from benchmark_data import write_new


def file_sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def verified_blob(root, descriptor):
    digest = descriptor["digest"]
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError("Expected a SHA-256 content-addressed blob")
    path = root / "blobs" / digest.replace(":", "-")
    if path.stat().st_size != descriptor["size"] or file_sha256(path) != digest[7:]:
        raise ValueError(f"Blob hash or size mismatch: {digest}")
    return path


def convert_tensor(source, destination):
    """Rename scale keys for mlx-lm; preserve every packed data byte."""
    with source.open("rb") as incoming:
        size = struct.unpack("<Q", incoming.read(8))[0]
        if size < 2 or size > 16 * 1024 * 1024 or size + 8 > source.stat().st_size:
            raise ValueError("Invalid safetensors header size")
        header = json.loads(incoming.read(size))
        renamed = {}
        for key, value in header.items():
            if key.endswith(".weight.scale"):
                key = key[:-len(".weight.scale")] + ".scales"
            elif key.endswith(".weight.global_scale"):
                key = key[:-len(".weight.global_scale")] + ".global_scale"
            if key in renamed:
                raise ValueError("Scale normalization produced duplicate tensor names")
            renamed[key] = value
        encoded = json.dumps(renamed, separators=(",", ":")).encode()
        encoded += b" " * (-len(encoded) % 8)
        with destination.open("xb") as outgoing:
            outgoing.write(struct.pack("<Q", len(encoded)))
            outgoing.write(encoded)
            shutil.copyfileobj(incoming, outgoing, 8 * 1024 * 1024)
    return [key for key in renamed if key != "__metadata__"]


def import_model(root, model_digest, output):
    manifest_path = root / "blobs" / f"sha256-{model_digest}"
    if file_sha256(manifest_path) != model_digest:
        raise ValueError("Installed model manifest does not match the baseline digest")
    manifest = json.loads(manifest_path.read_text())
    if output.exists():
        raise FileExistsError("Model output already exists; preserve it")
    output.mkdir(parents=True)
    receipt = {
        "ollama_model_digest": model_digest, "mode": "packed-byte-preserving-text-only",
        "source_blobs": [], "output_files": {}, "skipped_auxiliary_tensors": 0,
    }
    index = {}
    for layer in manifest["layers"]:
        media = layer["mediaType"]
        name = layer.get("name", "")
        if media == "application/vnd.ollama.image.tensor":
            if name.startswith(("model.visual.", "vision_tower.", "mtp.")):
                receipt["skipped_auxiliary_tensors"] += 1
                continue
            if not name.startswith(("model.language_model.", "lm_head.")):
                raise ValueError(f"Unexpected text tensor: {name}")
            source = verified_blob(root, layer)
            filename = f"model-{len(receipt['source_blobs']):05}.safetensors"
            target = output / filename
            keys = convert_tensor(source, target)
            if set(keys).intersection(index):
                raise ValueError("Duplicate tensor in model shards")
            index.update({key: filename for key in keys})
        elif media == "application/vnd.ollama.image.json" and name in (
            "config.json", "tokenizer.json", "tokenizer_config.json", "vocab.json",
        ):
            source = verified_blob(root, layer)
            target = output / name
            if name == "config.json":
                config = json.loads(source.read_text())
                if config.get("model_type") != "qwen3_5":
                    raise ValueError("This importer supports Qwen 3.5 only")
                # Per-layer packing is inferred from the preserved scales and shapes.
                config.pop("quantization_config", None)
                config["quantization"] = {"bits": 4, "group_size": 16, "mode": "nvfp4"}
                write_new(target, config)
            else:
                with source.open("rb") as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
        else:
            continue
        receipt["source_blobs"].append({"name": name, "sha256": layer["digest"][7:]})
        receipt["output_files"][target.name] = file_sha256(target)
    for filename in ("config.json", "tokenizer.json", "tokenizer_config.json"):
        if not (output / filename).is_file():
            raise ValueError(f"Missing required model file: {filename}")
    if not index:
        raise ValueError("Installed manifest contains no text weights")
    write_new(output / "model.safetensors.index.json", {"weight_map": index})
    write_new(output / "conversion_receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.home() / ".ollama" / "models")
    parser.add_argument("--digest", required=True, help="Exact installed baseline model digest")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = import_model(args.root, args.digest, args.output)
    print(f"Imported {len(receipt['output_files'])} files from {args.digest}")
    print("Text weights are unchanged; tokenizer and packed tensor provenance are recorded.")


if __name__ == "__main__":
    main()
