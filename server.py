import os
import time
import urllib.request
import urllib.parse
import json
import yt_dlp
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import google.generativeai as genai

app = Flask(__name__)
CORS(app) 

print("-> Cloud Lyric-Translator API: កំណែទម្រង់តស៊ូជាមួយ YouTube!")

BASE_DIR = '/tmp/lyric_data'
MEDIA_DIR = os.path.join(BASE_DIR, 'media')
os.makedirs(MEDIA_DIR, exist_ok=True)

# ----------------------------------------------------
# ១. ផ្នែករៀបចំ API Key និង Gemini Models
# ----------------------------------------------------
def configure_gemini(api_key):
    if api_key and api_key.startswith("AIza"):
        genai.configure(api_key=api_key)
        return True
    return False

@app.route('/check_auth', methods=['POST'])
def check_auth(): 
    api_key = request.form.get('api_key', '').strip()
    if api_key.startswith("AIza") and len(api_key) > 30:
        return jsonify({'success': True, 'masked_key': f"{api_key[:8]}...{api_key[-5:]}"})
    return jsonify({'error': "API Key មិនត្រឹមត្រូវ!"})

@app.route('/get_models', methods=['POST'])
def get_models():
    api_key = request.form.get('api_key', '').strip()
    default_models = [{"val": "gemini-2.5-flash", "name": "⚡ 2.5 Flash (លឿន-អត់គាំង)"}]
    if not configure_gemini(api_key): return jsonify(default_models)
    try:
        models = genai.list_models()
        valid_models = []
        for m in models:
            if 'generatecontent' in [meth.lower() for meth in m.supported_generation_methods] and 'gemini' in m.name.lower():
                if any(x in m.name.lower() for x in ['vision', 'robotics', 'learnmath']): continue
                clean_val = m.name.replace('models/', '')
                icon = '⚡' if 'flash' in clean_val else '🧠'
                valid_models.append({"val": clean_val, "name": f"{icon} {clean_val.replace('gemini-', '')} ({'លឿន' if 'flash' in clean_val else 'ឆ្លាត'})"})
        valid_models.sort(key=lambda x: x['val'], reverse=True)
        return jsonify(valid_models if valid_models else default_models)
    except: return jsonify(default_models)

@app.route('/download_media', methods=['POST'])
def download_media():
    url = request.form.get('url', '').strip()
    if not url: return jsonify({'error': 'សូមបញ្ចូលលីង (URL)!'})
    
    try:
        # លុបឯកសារចាស់ៗ
        for f in os.listdir(MEDIA_DIR): os.remove(os.path.join(MEDIA_DIR, f))
        timestamp = str(int(time.time()))
        
        # 🎯 ក្បួនទាញយកសកល (Universal Downloader)
        # កូដនេះនឹងស្វែងរក Format សម្លេងដែលល្អបំផុតដោយស្វ័យប្រវត្តិ
        ydl_opts = {
            'format': 'bestaudio/best', 
            'outtmpl': os.path.join(MEDIA_DIR, f'audio_{timestamp}.%(ext)s'),
            'quiet': True,
            'nocheckcertificate': True,
            'noplaylist': True,
            # បន្ថែម Header ដើម្បីបន្លំខ្លួនជា Browser ពិតប្រាកដ ការពារ FB/TikTok Block
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Referer': 'https://www.google.com/',
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Media File')
            ext = info.get('ext', 'm4a')
            
        file_name = f"audio_{timestamp}.{ext}"
        return jsonify({
            'success': True, 
            'file_name': file_name, 
            'title': title, 
            'type': 'audio'
        })
        
    except Exception as e:
        err_msg = str(e).lower()
        print(f"Download Error: {err_msg}")
        
        # បើទាញមិនកើត ប្រាប់អ្នកប្រើប្រាស់អោយចំៗ
        if "forbidden" in err_msg or "confirm your age" in err_msg:
            return jsonify({'error': "⚠️ វេបសាយនេះបានរារាំង Server! សូមទាញយក MP3 រួចប្រើប៊ូតុង [📁 ឯកសារ] ជំនួសវិញ។"})
        
        return jsonify({'error': f"មិនអាចទាញយកបានទេ៖ អាចមកពីលីងខុស ឬវេបសាយបិទសិទ្ធិ។"})

    except Exception as e:
        return jsonify({'error': f"Error: {str(e)}"})

@app.route('/upload_media', methods=['POST'])
def upload_media():
    file = request.files.get('file')
    if not file: return jsonify({'error': 'មិនមាន File ទេ!'})
    try:
        for f in os.listdir(MEDIA_DIR): os.remove(os.path.join(MEDIA_DIR, f))
        filename = secure_filename(file.filename)
        timestamp = str(int(time.time()))
        new_filename = f"media_{timestamp}_{filename}"
        file.save(os.path.join(MEDIA_DIR, new_filename))
        return jsonify({'success': True, 'file_name': new_filename, 'title': filename, 'type': 'audio'})
    except: return jsonify({'error': 'Upload បរាជ័យ!'})

@app.route('/media/<filename>')
def serve_media(filename):
    return send_file(os.path.join(MEDIA_DIR, filename))

# ----------------------------------------------------
# ៣. ផ្នែកបកប្រែ (ស្នូល Gemini)
# ----------------------------------------------------
@app.route('/translate_lyrics', methods=['POST'])
def translate_lyrics():
    api_key = request.form.get('api_key', '').strip()
    text_content = request.form.get('text', '').strip()
    media_filename = request.form.get('media_file', '').strip()
    gemini_model = request.form.get('gemini_model', 'gemini-2.5-flash') 

    if not configure_gemini(api_key): return jsonify({'error': 'API Key មិនត្រឹមត្រូវ!'})
    
    try:
        model = genai.GenerativeModel(model_name=gemini_model)
        prompt = "You are a Khmer romance master. Translate these lyrics into DEEPLY EMOTIONAL and NATURAL Khmer prose (ភាសានិយាយ). Use 'បង' and 'អូន'. Format in clean HTML with <br>. Add a short story analysis at the top."
        
        contents = [prompt]
        if media_filename:
            path = os.path.join(MEDIA_DIR, media_filename)
            if os.path.exists(path):
                file_up = genai.upload_file(path=path)
                while file_up.state.name == "PROCESSING": time.sleep(2); file_up = genai.get_file(file_up.name)
                contents.append(file_up)
        
        if text_content: contents.append(f"Lyrics:\n{text_content}")
        
        response = model.generate_content(contents)
        return jsonify({'result_html': response.text.replace('```html', '').replace('```', '').strip()})
    except Exception as e:
        return jsonify({'error': f"បកប្រែបរាជ័យ: {str(e)}"})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)