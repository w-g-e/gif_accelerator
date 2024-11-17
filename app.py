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

# Route for the main page
@app.route('/')
def index():
    return render_template('index.html')

# Modified upload route to return JSON
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
        file.save(filepath)
        return jsonify({
            'success': True,
            'filename': filename,
            'url': url_for('uploaded_file', filename=filename)
        })
    
    return jsonify({'error': 'File is not a GIF'}), 400

# New route to process GIFs
@app.route('/process_gif', methods=['POST'])
def process_gif():
    try:
        # Get the speed adjustment value from the request
        speed = float(request.form.get('speed', 0))
        filename = request.form.get('filename')
        
        if not filename:
            return jsonify({'error': 'No filename provided'}), 400
        
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        if not os.path.exists(input_path):
            return jsonify({'error': 'File not found'}), 404
        
        # Process the GIF
        processed_gif = adjust_gif_speed(input_path, speed)
        
        # Generate a unique filename for the processed GIF
        timestamp = int(time.time())
        processed_filename = f"processed_{timestamp}_{filename}"
        processed_path = os.path.join(app.config['UPLOAD_FOLDER'], processed_filename)
        
        # Save the processed GIF
        with open(processed_path, 'wb') as f:
            f.write(processed_gif)
        
        # Return the URL for the processed GIF
        return jsonify({
            'success': True,
            'processed_url': url_for('uploaded_file', filename=processed_filename)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Route to display the uploaded file
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)