from .nodes import VSCOScraperNode, VSCOCropNode, VSCOSelectNode

NODE_CLASS_MAPPINGS = {
    "VSCOScraper": VSCOScraperNode,
    "VSCOCrop": VSCOCropNode,
    "VSCOSelect": VSCOSelectNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VSCOScraper": "VSCO Scraper",
    "VSCOCrop": "VSCO Crop Padding",
    "VSCOSelect": "VSCO Select Image",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
