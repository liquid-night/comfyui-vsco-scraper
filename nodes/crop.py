class VSCOCropNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vsco_data": ("VSCO_SIZES",),
            }
        }

    RETURN_TYPES = ("IMAGE", "VSCO_SIZES")
    RETURN_NAMES = ("images", "vsco_data")
    OUTPUT_IS_LIST = (True, False)
    FUNCTION = "crop"
    CATEGORY = "VSCO"

    def crop(self, vsco_data):
        batch = vsco_data["images"]
        sizes = vsco_data["sizes"]
        cropped = [batch[i:i+1, :h, :w, :] for i, (h, w) in enumerate(sizes)]

        return (cropped, {"images": cropped, "sizes": sizes})
