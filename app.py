from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from PIL import Image
import numpy as np
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

def basic_blend_frames(frame1, frame2, alpha):
    """
    Basic interpolation - pure alpha blend between frames with format conversion
    """
    try:
        # Convert both frames to RGB mode to ensure consistent format
        if frame1.mode != 'RGB':
            frame1 = frame1.convert('RGB')
        if frame2.mode != 'RGB':
            frame2 = frame2.convert('RGB')
            
        # Convert frames to numpy arrays
        f1 = np.array(frame1).astype('float32')
        f2 = np.array(frame2).astype('float32')
        
        # Linear blend
        blended = (1 - alpha) * f1 + alpha * f2
        
        # Convert back to uint8 and create new frame
        return Image.fromarray(blended.astype('uint8'))
    except Exception as e:
        print(f"Error in basic_blend_frames: {str(e)}")
        print(f"Frame1 mode: {frame1.mode}, Frame2 mode: {frame2.mode}")
        print(f"Frame1 size: {frame1.size}, Frame2 size: {frame2.size}")
        raise

def adjust_gif_speed_simple(input_path, speed_factor):
    """Original simple frame duration adjustment"""
    if speed_factor > 0:
        multiplier = 1 / (1 + (speed_factor / 10) * 0.9)
    elif speed_factor < 0:
        multiplier = abs(1 - (speed_factor / 10))
    else:
        multiplier = 1

    img = Image.open(input_path)
    frames = []
    durations = []
    
    try:
        while True:
            duration = img.info.get('duration', 100)
            frames.append(img.copy())
            durations.append(int(duration * multiplier))
            img.seek(img.tell() + 1)
    except EOFError:
        pass

    output_buffer = io.BytesIO()
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

def adjust_gif_speed_with_interpolation(input_path, speed_factor):
    """Interpolated frame blending for smooth slow motion"""
    try:
        print(f"\nStarting GIF processing with speed_factor: {speed_factor}")
        
        # Only interpolate for slowdown
        if speed_factor >= 0:
            return adjust_gif_speed_simple(input_path, speed_factor)

        # Calculate multiplier
        multiplier = abs(1 - (speed_factor / 10))
        print(f"Calculated multiplier: {multiplier}")

        # Open the GIF file
        img = Image.open(input_path)
        frames = []
        durations = []
        
        try:
            while True:
                current_frame = img.copy()
                if img.mode != 'RGB':
                    current_frame = current_frame.convert('RGB')
                frames.append(current_frame)
                durations.append(img.info.get('duration', 100))
                img.seek(img.tell() + 1)
        except EOFError:
            pass

        print(f"Extracted {len(frames)} original frames")
        
        # Create interpolated frames
        interpolated_frames = []
        interpolated_durations = []
        base_duration = durations[0]
        
        # More proportional calculation:
        # -1 → 1 frame
        # -5 → 2 frames
        # -10 → 3 frames
        frames_to_insert = 1 + int(abs(speed_factor) / 5)
        print(f"Will insert {frames_to_insert} frames between each pair")
        
        # Process frame pairs
        for i in range(len(frames) - 1):
            # Add original frame
            interpolated_frames.append(frames[i])
            new_duration = int(base_duration * (1 + abs(speed_factor) / 10))
            interpolated_durations.append(new_duration)
            
            # Add interpolated frames
            for j in range(frames_to_insert):
                alpha = (j + 1) / (frames_to_insert + 1)
                blended_frame = basic_blend_frames(frames[i], frames[i + 1], alpha)
                interpolated_frames.append(blended_frame)
                interpolated_durations.append(new_duration)
        
        # Add final frame
        interpolated_frames.append(frames[-1])
        interpolated_durations.append(new_duration)
        
        print(f"Created {len(interpolated_frames)} interpolated frames")

        # Create output buffer
        output_buffer = io.BytesIO()
        
        # Save the modified GIF
        interpolated_frames[0].save(
            output_buffer,
            format='GIF',
            save_all=True,
            append_images=interpolated_frames[1:],
            duration=interpolated_durations,
            loop=0,
            optimize=False
        )
        
        return output_buffer.getvalue()

    except Exception as e:
        print(f"Error in adjust_gif_speed_with_interpolation: {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise

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
        print("Received process request:", request.form)
        print("Current processed_files dictionary:", processed_files)
        
        speed = float(request.form.get('speed', 0))
        filename = request.form.get('filename')
        use_interpolation = request.form.get('use_interpolation', 'false').lower() == 'true'
        
        print(f"Processing GIF with speed {speed}, filename {filename}, interpolation: {use_interpolation}")
        
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
        
        # Process the GIF using selected method
        print(f"Starting GIF processing with {'interpolation' if use_interpolation else 'simple'} method...")
        if use_interpolation:
            processed_gif = adjust_gif_speed_with_interpolation(input_path, speed)
        else:
            processed_gif = adjust_gif_speed_simple(input_path, speed)
        
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
        
        return jsonify({
            'success': True,
            'processed_url': url_for('uploaded_file', filename=processed_filename)
        })
        
    except Exception as e:
        print("Error in process_gif:")
        import traceback
        print(traceback.format_exc())
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