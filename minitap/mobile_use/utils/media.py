import json
from pathlib import Path

from PIL import Image


def quantize_and_save_gif(
    images: list[Image.Image],
    output_path: Path,
    colors: int = 128,
    duration: int = 100,
) -> None:
    """
    Quantize images and save as an optimized GIF.

    Args:
        images: List of PIL Image objects to convert to GIF
        output_path: Path where the GIF will be saved
        colors: Number of colors to use in quantization (lower = smaller file)
        duration: Duration of each frame in milliseconds

    Raises:
        ValueError: If images list is empty
    """
    if not images:
        raise ValueError("images must not be empty")

    quantized_images = []
    for img in images:
        if img.mode != "RGB":
            img = img.convert("RGB")
        quantized = img.quantize(colors=colors, method=2)
        quantized_images.append(quantized)

    quantized_images[0].save(
        output_path,
        save_all=True,
        append_images=quantized_images[1:],
        loop=0,
        optimize=True,
        duration=duration,
    )


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
    quantize_and_save_gif(images, gif_path)
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
