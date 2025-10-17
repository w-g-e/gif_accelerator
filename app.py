from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify
from PIL import Image
import numpy as np
import os
import io
import time
import threading
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename

app = Flask(__name__)

# Security configuration
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB file size limit
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['PROCESSING_TIMEOUT'] = 30  # 30 seconds processing timeout
app.config['CLEANUP_INTERVAL'] = 300  # 5 minutes cleanup interval
app.config['FILE_MAX_AGE'] = 1800  # 30 minutes max file age

UPLOAD_FOLDER = app.config['UPLOAD_FOLDER']
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


# Note: Advanced timeout implementation would require threading or multiprocessing
# For now, we rely on reasonable frame limits in the GIF processing functions

def validate_file_size(file_stream):
    """Validate file size without loading entire file into memory"""
    file_stream.seek(0, 2)  # Seek to end
    size = file_stream.tell()
    file_stream.seek(0)  # Reset to beginning

    max_size = app.config['MAX_CONTENT_LENGTH']
    if size > max_size:
        raise ValueError(f"File size ({size} bytes) exceeds maximum allowed size ({max_size} bytes)")

    return size

def basic_blend_frames(frame1, frame2, alpha):
    try:
        if frame1.mode != 'RGB':
            frame1 = frame1.convert('RGB')
        if frame2.mode != 'RGB':
            frame2 = frame2.convert('RGB')
        f1 = np.array(frame1).astype('float32')
        f2 = np.array(frame2).astype('float32')
        blended = (1 - alpha) * f1 + alpha * f2
        return Image.fromarray(blended.astype('uint8'))
    except Exception as e:
        print(f"Error in basic_blend_frames: {str(e)}")
        print(f"Frame1 mode: {frame1.mode}, Frame2 mode: {frame2.mode}")
        print(f"Frame1 size: {frame1.size}, Frame2 size: {frame2.size}")
        raise

def adjust_gif_speed_simple(input_path, speed_factor):
    if speed_factor > 0:
        multiplier = 1 / (1 + (speed_factor / 10) * 0.9)
    elif speed_factor < 0:
        # Ensure multiplier doesn't become too small to avoid division by zero
        multiplier = max(0.1, abs(1 - (speed_factor / 10)))
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
    finally:
        img.close()  # Ensure image is properly closed

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
    try:
        print(f"\nStarting GIF processing with speed_factor: {speed_factor}")
        
        if speed_factor >= 0:
            return adjust_gif_speed_simple(input_path, speed_factor)

        multiplier = abs(1 - (speed_factor / 10))
        print(f"Calculated multiplier: {multiplier}")

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
        finally:
            img.close()  # Ensure image is properly closed

        print(f"Extracted {len(frames)} original frames")
        
        interpolated_frames = []
        interpolated_durations = []
        base_duration = durations[0]
        
        frames_to_insert = 1 + int(abs(speed_factor) / 5)
        print(f"Will insert {frames_to_insert} frames between each pair")
        for i in range(len(frames) - 1):
            interpolated_frames.append(frames[i])
            new_duration = int(base_duration * (1 + abs(speed_factor) / 10))
            interpolated_durations.append(new_duration)
            for j in range(frames_to_insert):
                alpha = (j + 1) / (frames_to_insert + 1)
                blended_frame = basic_blend_frames(frames[i], frames[i + 1], alpha)
                interpolated_frames.append(blended_frame)
                interpolated_durations.append(new_duration)
        interpolated_frames.append(frames[-1])
        interpolated_durations.append(new_duration)
        
        print(f"Created {len(interpolated_frames)} interpolated frames")

        output_buffer = io.BytesIO()
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

def cleanup_old_files():
    """Clean up files older than FILE_MAX_AGE"""
    try:
        upload_folder = app.config['UPLOAD_FOLDER']
        max_age = app.config['FILE_MAX_AGE']
        current_time = time.time()
        
        if not os.path.exists(upload_folder):
            return
            
        files_cleaned = 0
        for filename in os.listdir(upload_folder):
            file_path = os.path.join(upload_folder, filename)
            
            # Security check: ensure file is within upload directory
            if not os.path.abspath(file_path).startswith(os.path.abspath(upload_folder)):
                continue
                
            if os.path.isfile(file_path):
                file_age = current_time - os.path.getmtime(file_path)
                if file_age > max_age:
                    try:
                        os.remove(file_path)
                        files_cleaned += 1
                        print(f"Cleaned up old file: {filename} (age: {file_age:.1f}s)")
                    except OSError as e:
                        print(f"Error cleaning up {filename}: {e}")
        
        if files_cleaned > 0:
            print(f"Session cleanup: removed {files_cleaned} old files")
            
    except Exception as e:
        print(f"Error in cleanup_old_files: {e}")

def start_cleanup_scheduler():
    """Start background thread for periodic cleanup"""
    def cleanup_worker():
        while True:
            try:
                cleanup_old_files()
                time.sleep(app.config['CLEANUP_INTERVAL'])
            except Exception as e:
                print(f"Error in cleanup worker: {e}")
                time.sleep(60)  # Wait 1 minute before retrying
    
    cleanup_thread = threading.Thread(target=cleanup_worker, daemon=True)
    cleanup_thread.start()
    print("Started session-based cleanup scheduler")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        # Validate file size
        try:
            file_size = validate_file_size(file.stream)
        except ValueError as e:
            return jsonify({'error': str(e)}), 413

        # Validate file type
        if not (file and file.filename.lower().endswith('.gif')):
            return jsonify({'error': 'File must be a GIF'}), 400

        # Validate GIF header (magic bytes)
        file.stream.seek(0)
        header = file.stream.read(6)
        file.stream.seek(0)

        if not (header.startswith(b'GIF87a') or header.startswith(b'GIF89a')):
            return jsonify({'error': 'Invalid GIF file format'}), 400

        filename = secure_filename(file.filename)
        if not filename:
            return jsonify({'error': 'Invalid filename'}), 400

        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Security check: ensure the resolved path is within upload directory
        if not os.path.abspath(filepath).startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])):
            return jsonify({'error': 'Invalid file path'}), 400

        file.save(filepath)
        
        # Update file timestamp to mark as recently used
        os.utime(filepath, None)
        
        return jsonify({
            'success': True,
            'filename': filename,
            'url': url_for('uploaded_file', filename=filename),
            'size': file_size
        })

    except Exception as e:
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/process_gif', methods=['POST'])
def process_gif():
    try:
        print("Received process request:", request.form)

        # Validate speed parameter
        try:
            speed = float(request.form.get('speed', 0))
            if not -10 <= speed <= 10:
                return jsonify({'error': 'Speed parameter must be between -10 and 10'}), 400
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid speed parameter'}), 400

        filename = request.form.get('filename')
        use_interpolation = request.form.get('use_interpolation', 'false').lower() == 'true'

        print(f"Processing GIF with speed {speed}, filename {filename}, interpolation: {use_interpolation}")

        if not filename:
            return jsonify({'error': 'No filename provided'}), 400

        # Sanitize filename
        filename = secure_filename(filename)
        if not filename:
            return jsonify({'error': 'Invalid filename'}), 400

        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Security check: ensure the resolved path is within upload directory
        if not os.path.abspath(input_path).startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])):
            return jsonify({'error': 'Invalid file path'}), 400
            
        print(f"Looking for input file at: {input_path}")

        if not os.path.exists(input_path):
            return jsonify({'error': 'File not found'}), 404

        return jsonify({
            'success': True,
            'processed_url': url_for('download_processed', filename=filename, speed=speed, use_interpolation=use_interpolation),
            'cleanup_original': True
        })

    except Exception as e:
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/download_processed/<filename>')
def download_processed(filename):
    try:
        speed = float(request.args.get('speed', 0))
        use_interpolation = request.args.get('use_interpolation', 'false').lower() == 'true'

        # Validate speed parameter bounds
        if not -10 <= speed <= 10:
            return jsonify({'error': 'Speed parameter must be between -10 and 10'}), 400

        filename = secure_filename(filename)
        if not filename:
            return jsonify({'error': 'Invalid filename'}), 400

        input_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Security check: ensure the resolved path is within upload directory
        if not os.path.abspath(input_path).startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])):
            return jsonify({'error': 'Invalid file path'}), 400

        if not os.path.exists(input_path):
            return jsonify({'error': 'File not found'}), 404

        print(f"Streaming processed GIF with speed {speed}, interpolation: {use_interpolation}")
        
        # Update file timestamp to mark as recently used
        os.utime(input_path, None)

        try:
            if use_interpolation:
                processed_gif = adjust_gif_speed_with_interpolation(input_path, speed)
            else:
                processed_gif = adjust_gif_speed_simple(input_path, speed)
        except Exception as processing_error:
            return jsonify({'error': f'Processing failed: {str(processing_error)}'}), 500

        return app.response_class(
            processed_gif,
            mimetype='image/gif',
            headers={
                'Content-Disposition': f'attachment; filename="processed_{filename}"'
            }
        )

    except ValueError as e:
        return jsonify({'error': f'Invalid parameter: {str(e)}'}), 400
    except Exception as e:
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    filename = secure_filename(filename)
    if not filename:
        return jsonify({'error': 'Invalid filename'}), 400
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/cleanup_original/<filename>', methods=['POST'])
def cleanup_original(filename):
    try:
        filename = secure_filename(filename)
        if not filename:
            return jsonify({'error': 'Invalid filename'}), 400

        original_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Security check: ensure the resolved path is within upload directory
        if not os.path.abspath(original_path).startswith(os.path.abspath(app.config['UPLOAD_FOLDER'])):
            return jsonify({'error': 'Invalid file path'}), 400
            
        if os.path.exists(original_path):
            os.remove(original_path)
            print(f"Cleaned up original file: {filename}")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': 'Cleanup failed'}), 500

@app.route('/cleanup_old_files', methods=['POST'])
def manual_cleanup():
    """Manual cleanup endpoint for testing or admin use"""
    try:
        cleanup_old_files()
        return jsonify({'success': True, 'message': 'Cleanup completed'})
    except Exception as e:
        return jsonify({'error': f'Cleanup failed: {str(e)}'}), 500

# Flask error handlers for better security
@app.errorhandler(413)
def request_entity_too_large(error):
    return jsonify({'error': 'File too large. Maximum size is 10MB.'}), 413

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    # Clean up any existing old files on startup
    print("Starting GIF Accelerator...")
    cleanup_old_files()
    
    # Start the background cleanup scheduler
    start_cleanup_scheduler()
    
    app.run(debug=True, port=8080)