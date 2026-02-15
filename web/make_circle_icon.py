import os
from PIL import Image, ImageOps

logo_path = r"d:\CytechMusic\docs\logo.jpeg"
output_path = r"d:\CytechMusic\docs\logo-circle.png"

try:
    if not os.path.exists(logo_path):
        print(f"Error: {logo_path} not found.")
        exit(1)

    img = Image.open(logo_path).convert("RGBA")
    
    # Create circular mask
    mask = Image.new("L", img.size, 0)
    import  re
    from PIL import ImageDraw
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0) + img.size, fill=255)
    
    # Apply mask
    output = ImageOps.fit(img, mask.size, centering=(0.5, 0.5))
    output.putalpha(mask)
    
    output.save(output_path, "PNG")
    print(f"Successfully created {output_path}")

except Exception as e:
    print(f"An error occurred: {e}")
