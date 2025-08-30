import base64
import json
from io import BytesIO
from pathlib import Path

from PIL import Image


def compress_base64_jpeg(base64_str: str, quality: int = 50) -> str:
    if base64_str.startswith("data:image"):
        base64_str = base64_str.split(",")[1]

    image_data = base64.b64decode(base64_str)
    image = Image.open(BytesIO(image_data))

    compressed_io = BytesIO()
    image.save(compressed_io, format="JPEG", quality=quality, optimize=True)

    compressed_base64 = base64.b64encode(compressed_io.getvalue()).decode("utf-8")
    return compressed_base64


def create_gif_from_trace_folder(trace_folder_path: Path):
    images = []
    image_files = []

    for file in trace_folder_path.iterdir():
        if file.suffix == ".jpeg":
            image_files.append(file)

    image_files.sort(key=lambda f: int(f.stem))

    print("Found " + str(len(image_files)) + " images to compile")

    for file in image_files:
        with open(file, "rb") as f:
            image = Image.open(f).convert("RGB")
            images.append(image)

    if len(images) == 0:
        return

    gif_path = trace_folder_path / "trace.gif"
    images[0].save(gif_path, save_all=True, append_images=images[1:], loop=0)
    print("GIF created at " + str(gif_path))


def remove_images_from_trace_folder(trace_folder_path: Path):
    for file in trace_folder_path.iterdir():
        if file.suffix == ".jpeg":
            file.unlink()


def create_steps_json_from_trace_folder(trace_folder_path: Path):
    steps = []
    for file in trace_folder_path.iterdir():
        if file.suffix == ".json":
            with open(file, encoding="utf-8", errors="ignore") as f:
                json_content = f.read()
                steps.append({"timestamp": int(file.stem), "data": json_content})

    steps.sort(key=lambda f: f["timestamp"])

    print("Found " + str(len(steps)) + " steps to compile")

    with open(trace_folder_path / "steps.json", "w", encoding="utf-8", errors="ignore") as f:
        f.write(json.dumps(steps))


def remove_steps_json_from_trace_folder(trace_folder_path: Path):
    for file in trace_folder_path.iterdir():
        if file.suffix == ".json" and file.name != "steps.json":
            file.unlink()
