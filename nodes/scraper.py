import concurrent.futures
import tempfile
from pathlib import Path

import torch

from ..lib import IMAGE_EXTS, PLAYWRIGHT_AVAILABLE, ensure_chrome, load_image_tensor, run_playwright


class VSCOScraperNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "username": ("STRING", {"default": ""}),
            },
            "optional": {
                "output_dir": ("STRING", {"default": "",
                    "tooltip": "Directory to save downloaded images. Defaults to system temp/vsco-downloads/<username>."}),
                "max_images": ("INT", {"default": 0, "min": 0, "max": 10000, "step": 1,
                    "tooltip": "Maximum number of images to load as output. 0 = all."}),
                "include_videos": ("BOOLEAN", {"default": False}),
                "force_refresh": ("BOOLEAN", {"default": False,
                    "tooltip": "Re-scrape even if images already exist on disk."}),
            }
        }

    RETURN_TYPES = ("IMAGE", "VSCO_SIZES")
    RETURN_NAMES = ("images", "vsco_data")
    FUNCTION = "scrape"
    CATEGORY = "VSCO"

    @classmethod
    def IS_CHANGED(cls, username, output_dir="", max_images=0, include_videos=False, force_refresh=False):
        return hash((username.strip().lstrip("@"), output_dir, max_images, include_videos, force_refresh))

    def scrape(self, username, output_dir="", max_images=0, include_videos=False, force_refresh=False):
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("playwright is not installed. Run: pip install playwright && playwright install chromium")

        username = username.strip().lstrip("@")

        if not username:
            raise ValueError("username cannot be empty.")

        out = Path(output_dir).expanduser() if output_dir else Path(tempfile.gettempdir()) / "vsco-downloads" / username
        out.mkdir(parents=True, exist_ok=True)

        existing = [p for p in out.iterdir() if p.suffix.lower() in IMAGE_EXTS]

        if existing and (max_images == 0 or len(existing) >= max_images) and not force_refresh:
            print(f"Found {len(existing)} cached images, skipping scrape.")
        else:
            ensure_chrome()

            from comfy.utils import ProgressBar

            pbar = ProgressBar(100)
            prev_pct = [0]

            def on_progress(completed, total):
                pct = int(completed / total * 100)
                pbar.update(pct - prev_pct[0])
                prev_pct[0] = pct

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(run_playwright, username, out, include_videos, max_images, on_progress).result()

        image_files = sorted(p for p in out.iterdir() if p.suffix.lower() in IMAGE_EXTS)

        if max_images > 0:
            image_files = image_files[:max_images]

        if not image_files:
            raise ValueError(f"No image files found in {out}")

        print(f"Loading {len(image_files)} images...")

        tensors = []

        for p in image_files:
            try:
                tensors.append(load_image_tensor(p))
            except Exception as e:
                print(f"Skipping {p.name}: {e}")

        if not tensors:
            raise ValueError("No images could be loaded.")

        sizes = [(t.shape[0], t.shape[1]) for t in tensors]
        max_h = max(h for h, _ in sizes)
        max_w = max(w for _, w in sizes)
        padded = [torch.nn.functional.pad(t, (0, 0, 0, max_w - t.shape[1], 0, max_h - t.shape[0])) for t in tensors]
        batch = torch.stack(padded)

        return (batch, {"images": batch, "sizes": sizes})
