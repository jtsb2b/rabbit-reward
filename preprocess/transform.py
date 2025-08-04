import fitz  # PyMuPDF
import re
import json
import os

# --- Configuration ---
PDF_FILE = "/Users/jullajakkarnjanaekarin/Documents/rabbit-reward/preprocess/2025 RR CRM-Call Center FAQ_Scripts [29.7.2025].pdf_page_81-200.pdf"
INPUT_FILE = "/Users/jullajakkarnjanaekarin/Documents/rabbit-reward/preprocess/data-3.txt" # This should be the raw text with <q> and <a> tags
OUTPUT_FILE = "/Users/jullajakkarnjanaekarin/Documents/rabbit-reward/output-data-3.jsonl"
IMG_DIR = "img"

# Global counter for unique image filenames
image_counter = 1

def crop_and_save_image(page_num_str, coords_str, img_filename):
    """
    Crops a specific area from a page in the source PDF and saves it as an image file.
    """
    os.makedirs(IMG_DIR, exist_ok=True)
    
    try:
        x, y, w, h = [float(c.strip()) for c in coords_str.split(',')]
        page_index = int(page_num_str) - 1
    except (ValueError, TypeError) as e:
        print(f"Warning: Could not parse page/coordinates '{page_num_str}'/'{coords_str}'. Skipping image. Error: {e}")
        return None

    try:
        doc = fitz.open(PDF_FILE)
        if page_index >= len(doc):
             print(f"Warning: Page {page_num_str} is out of bounds for PDF '{PDF_FILE}'. Skipping image.")
             doc.close()
             return None
        
        page = doc.load_page(page_index)
        clip_rect = fitz.Rect(x, y, x + w, y + h)
        pix = page.get_pixmap(clip=clip_rect, dpi=300)
        output_path = os.path.join(IMG_DIR, img_filename)
        pix.save(output_path)
        doc.close()
        return img_filename
    except Exception as e:
        print(f"Error processing image on page {page_num_str} with coords {coords_str}: {e}")
        return None

def replacer_callback(match):
    """
    Callback function for re.sub. Called for each image tag found.
    Processes the image and returns the placeholder string for replacement.
    """
    global image_counter
    
    page_num, coords_str, caption = match.groups()
    img_filename = f"IMG-{image_counter:03d}.jpg"
    
    saved_file = crop_and_save_image(page_num, coords_str, img_filename)
    
    if saved_file:
        print(f"  > Cropped and saved image: {saved_file} from page {page_num}")
        image_counter += 1
        placeholder = f"<img-name>{saved_file}</img-name><caption>{caption}</caption>"
    else:
        print(f"  > FAILED to process image on page {page_num}.")
        placeholder = f"[IMAGE PROCESSING FAILED FOR PAGE {page_num}]"

    return placeholder

def process_text_chunk(text_chunk):
    """Processes a chunk of text to find and replace all image tags."""
    if not text_chunk or not text_chunk.strip():
        return ""
    
    img_pattern = r"<page>(\d+)</page><img>\((.*?)\)</img><caption>(.*?)</caption>"
    # Use re.sub with the callback function to handle all matches
    processed_text = re.sub(img_pattern, replacer_callback, text_chunk)
    return processed_text.strip()

def main():
    """Main function to read the entire input file, parse it in chunks, and write the output."""
    if not os.path.exists(PDF_FILE):
        print(f"Error: Source PDF file '{PDF_FILE}' not found.")
        return
    if not os.path.exists(INPUT_FILE):
        print(f"Error: Input file '{INPUT_FILE}' not found.")
        return

    print("Reading entire input file...")
    with open(INPUT_FILE, 'r', encoding='utf-8') as infile:
        full_content = infile.read()

    # Define the pattern to find Q&A blocks, allowing them to span newlines
    qa_pattern = re.compile(r"<q>(.*?)</q><a>(.*?)</a>", re.DOTALL)
    
    last_end = 0
    all_json_objects = []

    print("Parsing content and processing chunks...")
    # Find all Q&A blocks in the content
    for match in qa_pattern.finditer(full_content):
        # 1. Process plain text before the current Q&A match
        plain_text_chunk = full_content[last_end:match.start()]
        processed_text = process_text_chunk(plain_text_chunk)
        if processed_text:
            print("  > Found a plain text block.")
            all_json_objects.append({"text": processed_text})

        # 2. Process the Q&A match itself
        print("  > Found a Q&A block.")
        q_raw, a_raw = match.groups()
        
        processed_q = process_text_chunk(q_raw)
        processed_a = process_text_chunk(a_raw)
        
        all_json_objects.append({"q": processed_q, "a": processed_a})

        # 3. Update the pointer for the next iteration
        last_end = match.end()

    # 4. Process any remaining plain text after the last Q&A match
    remaining_text_chunk = full_content[last_end:]
    processed_text = process_text_chunk(remaining_text_chunk)
    if processed_text:
        print("  > Found a final plain text block.")
        all_json_objects.append({"text": processed_text})
        
    print("-" * 20)
    print(f"Writing {len(all_json_objects)} JSON objects to '{OUTPUT_FILE}'...")
    # Write all processed objects to the output file
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as outfile:
        for json_obj in all_json_objects:
            json.dump(json_obj, outfile, ensure_ascii=False)
            outfile.write('\n')
    
    print("Processing complete!")
    print(f"JSON Lines output has been saved to: {OUTPUT_FILE}")
    print(f"Cropped images have been saved to the '{IMG_DIR}/' directory.")

if __name__ == "__main__":
    main()