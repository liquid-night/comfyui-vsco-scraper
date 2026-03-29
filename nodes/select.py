class VSCOSelectNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vsco_data": ("VSCO_SIZES",),
                "index": ("INT", {"default": 0, "min": 0, "step": 1}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "select"
    CATEGORY = "VSCO"

    def select(self, vsco_data, index):
        images = vsco_data["images"]
        sizes = vsco_data["sizes"]
        count = len(images) if isinstance(images, list) else images.shape[0]

        if index >= count:
            raise ValueError(f"Index {index} out of range ({count} images).")

        if isinstance(images, list):
            return (images[index],)

        h, w = sizes[index]

        return (images[index:index+1, :h, :w, :],)
