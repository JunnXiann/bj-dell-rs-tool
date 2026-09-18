import os
import argparse
from PIL import Image

def convert_images_to_jpg(folder_path: str) -> None:
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)

        if not os.path.isfile(file_path):
            continue

        name, ext = os.path.splitext(filename)
        ext = ext.lower()

        if ext == '.jpg' or ext == '.jpeg':
            continue  # Already JPG, skip

        try:
            with Image.open(file_path) as img:
                if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                    # Create white background
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.convert('RGBA').split()[-1])
                    rgb_img = background

                else:
                    rgb_img = img.convert('RGB')
                jpg_path = os.path.join(folder_path, f"{name}.jpg")
                rgb_img.save(jpg_path, 'JPEG')
                print(f"Converted {filename} to {name}.jpg")
                
        except Exception as e:
            print(f"Failed to convert {filename}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert images in a folder to JPG.")
    parser.add_argument("folder", type=str, help="Path to the folder containing images")
    args = parser.parse_args()
    convert_images_to_jpg(args.folder)