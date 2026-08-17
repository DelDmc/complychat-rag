import shutil
import os

def rename_files_for_web(in_dir, out_dir):
    # Check if output directory exists, if not create it
    if not os.path.exists(out_dir):
        os.makedirs(out_dir)
        
    for filename in os.listdir(in_dir):
        # Replace spaces, commas, slashes, and points with underscores
        new_filename = filename \
            .replace(" ", "_") \
            .replace(",", "_") \
            .replace("/", "_") \
            .replace("-", "_") \
            .replace("‘", "") \
            .replace("'", "") \
            .replace("–", "") \
            .replace("-", "_") \
            .replace("’", "") \
            .replace(")", "") \
            .replace("(", "") \
            .replace(":", "_") 
       
        # Construct full file path
        old_file_path = os.path.join(in_dir, filename)
        new_file_path = os.path.join(out_dir, new_filename)
        
        # Copy and rename the file to the new directory
        shutil.copy2(old_file_path, new_file_path)
    print(f"All files in {in_dir} have been renamed for web operations and moved to {out_dir}.")


if __name__ == "__main__":
    out_dir = 'app/documents/files/comply_sources/'
    in_dir = 'app/documents/files/comply_sources_original/'
    rename_files_for_web(in_dir, out_dir)
    
