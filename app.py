from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from PIL import Image
import os
import io
import time
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Define the path where uploaded files will be stored
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Dictionary to track processed files for each original file
processed_files = {}

def cleanup_old_processed_file(original_filename):
    """Delete the old processed file if it exists"""
    if original_filename in processed_files and processed_files[original_filename] is not None:
        old_processed_path = os.path.join(app.config['UPLOAD_FOLDER'], processed_files[original_filename])
        try:
            if os.path.exists(old_processed_path):
                os.remove(old_processed_path)
                print(f"Deleted old processed file: {processed_files[original_filename]}")
        except Exception as e:
            print(f"Error deleting old file: {e}")
def adjust_gif_speed(input_path, speed_factor):
    """
    Adjust the speed of a GIF file by modifying frame durations.
    
    Args:
        input_path: Path to the input GIF file
        speed_factor: Float between -10 and 10 where:
            0 = original speed
            positive = faster
            negative = slower
    
    Returns:
        bytes: The processed GIF file as bytes
    """
    # Convert speed_factor to a multiplier (e.g., 2x speed, 0.5x speed)
    if speed_factor > 0:
        # For positive values (faster), reduce duration (1 to 0.1x)
        multiplier = 1 / (1 + (speed_factor / 10) * 0.9)
    elif speed_factor < 0:
        # For negative values (slower), increase duration (1 to 10x)
        multiplier = 1 - (speed_factor / 10)
    else:
        # No change
        multiplier = 1

    # Open the GIF file
    img = Image.open(input_path)
    
    # Extract frames and their durations
    frames = []
    durations = []
    
    try:
        while True:
            # Get current frame duration in milliseconds
            duration = img.info.get('duration', 100)  # default to 100ms if not specified
            
            # Create a copy of the current frame
            frame_copy = img.copy()
            
            # Adjust the duration by the multiplier
            new_duration = int(duration * multiplier)
            
            # Ensure minimum duration of 20ms to prevent ultra-fast GIFs
            new_duration = max(20, new_duration)
            
            frames.append(frame_copy)
            durations.append(new_duration)
            
            # Move to next frame
            img.seek(img.tell() + 1)
    except EOFError:
        pass  # We've reached the end of the frames

    # Create output buffer
    output_buffer = io.BytesIO()
    
    # Save the modified GIF
    frames[0].save(
        output_buffer,
        format='GIF',
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=False
    )
    
    return output_buffer.getvalue()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    if file and file.filename.endswith('.gif'):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Clean up any existing processed file for this upload
        cleanup_old_processed_file(filename)
        
        # Reset the processed file tracking for this new upload
        processed_files[filename] = None
        
        file.save(filepath)
        return jsonify({
            'success': True,
            'filename': filename,
            'url': url_for('uploaded_file', filename=filename)
        })
    
    return jsonify({'error': 'File is not a GIF'}), 400

@app.route('/process_gif', methods=['POST'])
def process_gif():
    try:
        # Print debug information
        print("Received process request:", request.form)
        print("Current processed_files dictionary:", processed_files)
        
        speed = float(request.form.get('speed', 0))
        filename = request.form.get('filename')
        
        print(f"Processing GIF with speed {speed} and filename {filename}")
        
        if not filename:
            return jsonify({'error': 'No filename provided'}), 400
        
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        print(f"Looking for input file at: {input_path}")
        
        if not os.path.exists(input_path):
            print(f"File not found at path: {input_path}")
            print(f"Contents of upload folder: {os.listdir(app.config['UPLOAD_FOLDER'])}")
            return jsonify({'error': f'File not found: {input_path}'}), 404
        
        # Clean up old processed file before creating new one
        print("Cleaning up old processed file...")
        cleanup_old_processed_file(filename)
        
        # Process the GIF
        print("Starting GIF processing...")
        processed_gif = adjust_gif_speed(input_path, speed)
        
        # Generate filename for the processed GIF
        processed_filename = f"processed_{filename}"
        processed_path = os.path.join(app.config['UPLOAD_FOLDER'], processed_filename)
        print(f"Saving processed GIF to: {processed_path}")
        
        # Save the processed GIF and update tracking
        with open(processed_path, 'wb') as f:
            f.write(processed_gif)
        
        # Update the tracking dictionary
        processed_files[filename] = processed_filename
        print(f"Updated processed_files dictionary: {processed_files}")
        
        result = jsonify({
            'success': True,
            'processed_url': url_for('uploaded_file', filename=processed_filename)
        })
        print("Returning success response")
        return result
        
    except Exception as e:
        import traceback
        print("Error in process_gif:")
        print(traceback.format_exc())  # This will print the full error traceback
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc()
        }), 500

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# Optional: Add cleanup on server shutdown
import atexit

@atexit.register
def cleanup_on_exit():
    """Clean up all processed files when the server shuts down"""
    for filename in processed_files.values():
        if filename:
            try:
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
            except Exception as e:
                print(f"Error cleaning up file {filename}: {e}")

if __name__ == '__main__':
    app.run(debug=True)