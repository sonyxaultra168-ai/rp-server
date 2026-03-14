import os
import json
import time
import yt_dlp
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import google.generativeai as genai

app = Flask(__name__)
# អនុញ្ញាតអោយ Frontend (APK) ភ្ជាប់មក Server នេះបានដោយមិនមានបញ្ហា Block
CORS(app) 

print("-> Cloud Lyric-Translator API ដំណើរការ!")

# ប្រើប្រាស់ /tmp ព្រោះ Cloud Server ឥតគិតថ្លៃភាគច្រើនអនុញ្ញាតអោយ Save ឯកសារតែក្នុងទីនេះទេ
BASE_DIR = '/tmp/lyric_data'
MEDIA_DIR = os.path.join(BASE_DIR, 'media')
os.makedirs(MEDIA_DIR, exist_ok=True)

# ----------------------------------------------------
# ផ្នែករៀបចំ API Key និង Gemini Models
# ----------------------------------------------------
def configure_gemini(api_key):
    if api_key:
        genai.configure(api_key=api_key)
        return True
    return False

@app.route('/get_models', methods=['POST'])
def get_models():
    api_key = request.form.get('api_key', '').strip()
    default_models = [{"val": "gemini-1.5-pro", "name": "🧠 1.5 Pro"}, {"val": "gemini-1.5-flash", "name": "⚡ 1.5 Flash"}]
    if not configure_gemini(api_key):
        return jsonify(default_models)
    
    try:
        models = genai.list_models()
        valid = []
        for m in models:
            name = m.name.lower()
            if 'generatecontent' in m.supported_generation_methods and 'gemini' in name and 'vision' not in name:
                clean_val = m.name.replace('models/', '')
                icon = '🧠' if 'pro' in clean_val else ('🔥' if '2.' in clean_val else '⚡')
                valid.append({"val": clean_val, "name": f"{icon} {clean_val.replace('gemini-', '')}"})
        return jsonify(valid if valid else default_models)
    except:
        return jsonify(default_models)

@app.route('/check_auth', methods=['POST'])
def check_auth(): 
    api_key = request.form.get('api_key', '').strip()
    if not api_key: return jsonify({'error': "សូមបញ្ចូល API Key!"})
    try:
        genai.configure(api_key=api_key)
        # 🎯 ប្រើវិធីនេះលឿនជាង និងមិនគាំង Server 
        genai.get_model('models/gemini-1.5-flash') 
        return jsonify({'success': True, 'masked_key': f"{api_key[:8]}...{api_key[-5:]}"})
    except Exception as e: 
        print(f"Auth Error: {str(e)}")
        return jsonify({'error': "API Key មិនត្រឹមត្រូវ ឬខូចហើយ!"})

# ----------------------------------------------------
# ផ្នែកទាញយក និង Upload ឯកសារ
# ----------------------------------------------------
@app.route('/download_media', methods=['POST'])
def download_media():
    url = request.form.get('url', '').strip()
    if not url: return jsonify({'error': 'សូមបញ្ចូល URL!'})
    try:
        # លុបឯកសារចាស់ៗ
        for f in os.listdir(MEDIA_DIR): os.remove(os.path.join(MEDIA_DIR, f))
        
        timestamp = str(int(time.time()))
        out_template = os.path.join(MEDIA_DIR, f'audio_{timestamp}.%(ext)s')
        
        # 🎯 ក្បួនបន្លំខ្លួន + ប្រើសំបុត្រ VIP (Cookies)
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': out_template,
            'quiet': True,
            'nocheckcertificate': True,
            'cookiefile': 'cookies.txt',  
            'extractor_args': {'youtube': ['player_client=android']}, 
            'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Unknown Song')
            ext = info.get('ext', 'm4a')
            
        file_name = f"audio_{timestamp}.{ext}"
        return jsonify({'success': True, 'file_name': file_name, 'title': title, 'type': 'audio'})
    except Exception as e:
        err_msg = str(e)
        if "bot" in err_msg.lower() or "sign in" in err_msg.lower():
            return jsonify({'error': "⚠️ YouTube កំពុងបិទ (Block) Server មិនអោយទាញយកបណ្ដោះអាសន្ន។ សូមប្រើប៊ូតុង [📁 ឯកសារ] សិនចុះបង!"})
        return jsonify({'error': f"មិនអាចទាញយកបានទេ: {err_msg}"})

@app.route('/upload_media', methods=['POST'])
def upload_media():
    if 'file' not in request.files: return jsonify({'error': 'មិនមាន File ទេ!'})
    file = request.files['file']
    if file.filename == '': return jsonify({'error': 'មិនមាន File ទេ!'})
    try:
        for f in os.listdir(MEDIA_DIR): os.remove(os.path.join(MEDIA_DIR, f))
        filename = secure_filename(file.filename)
        timestamp = str(int(time.time()))
        ext = filename.split('.')[-1].lower()
        new_filename = f"media_{timestamp}.{ext}"
        filepath = os.path.join(MEDIA_DIR, new_filename)
        file.save(filepath)
        file_type = 'video' if ext in ['mp4', 'mov', 'webm'] else 'audio'
        return jsonify({'success': True, 'file_name': new_filename, 'title': filename, 'type': file_type})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/media/<filename>')
def serve_media(filename):
    return send_file(os.path.join(MEDIA_DIR, filename))

# ----------------------------------------------------
# ផ្នែកខួរក្បាលបកប្រែ AI 
# ----------------------------------------------------
@app.route('/translate_lyrics', methods=['POST'])
def translate_lyrics():
    api_key = request.form.get('api_key', '').strip()
    text_content = request.form.get('text', '').strip()
    media_filename = request.form.get('media_file', '').strip()
    gemini_model = request.form.get('gemini_model', 'gemini-1.5-pro') 

    if not configure_gemini(api_key): return jsonify({'error': 'សូមបញ្ចូល API Key ជាមុនសិន!'})
    if not text_content and not media_filename: return jsonify({'error': 'សូមបញ្ចូលអត្ថបទចម្រៀង ឬ Media!'})

    try:
        model = genai.GenerativeModel(model_name=gemini_model, generation_config={"temperature": 0.5})
        
        prompt = """You are a master of modern Cambodian romance prose (អ្នកនិពន្ធប្រលោមលោកមនោសញ្ចេតនាខ្មែរ). Your task is to translate song lyrics into DEEPLY EMOTIONAL, HEARTFELT, and NATURAL prose (ភាសានិយាយប្រចាំថ្ងៃ).

        🔥 STRICT RULES FOR THE AI TO UNDERSTAND CONTEXT:
        1. CONCEPTUAL OVER LITERAL (យល់ន័យ មិនមែនប្រែពាក្យ): DO NOT translate English idioms, metaphors, or body parts (like "soul", "mind", "bones", "stars", "weather") literally. Instead, ask yourself: "How does a real Khmer person express this exact emotion?" Translate the FEELING into natural Khmer romantic prose.
        2. ABSOLUTELY NO POETRY (ហាមសរសេរជាកំណាព្យដាច់ខាត): AI struggles with Khmer rhyming. DO NOT try to make the words rhyme. Write it as smooth, flowing prose, like a heartfelt letter.
        3. GENDER & PRONOUNS: Use "បង" (Bong) and "អូន" (Oun) based on the singer's gender. DO NOT use "ខ្ញុំ" or "អ្នក".
        4. TWO-STEP METHOD: Always translate the core meaning to standard English first internally, then express that meaning in Khmer.
        5. CRITICAL FORMATTING: You MUST put a `<br>` directly after every tag like [Verse 1] or [Chorus]. The lyrics MUST start on the next line. DO NOT put lyrics on the same line as the tag!

        Output EXACTLY in this HTML format ONLY (no markdown ```):
        <div id="hidden-original-lyrics" style="display:none;">
            [Verse 1]
            Original line 1...
        </div>
        
        <div style="margin-bottom: 20px;">
            <div style="font-size: 14px; color: #4db6ac; font-weight: bold; margin-bottom: 5px;">🎵 ការវិភាគអត្ថន័យចម្រៀង (Song Analysis):</div>
            <div style="color: #cfd8dc; font-size: 13px; line-height: 1.6; background: #263238; padding: 10px; border-radius: 8px; border-left: 4px solid #4db6ac;">
                [Explain the story naturally in standard Khmer prose.]
            </div>
        </div>
        
        <div style="font-size: 15px; color: #ffffff; line-height: 2.0;">
            <span style="color: #f39c12; font-weight: bold;">[Verse 1]</span><br>
            [Natural Khmer Prose Line 1]<br>
            [Natural Khmer Prose Line 2]<br><br>
            
            <span style="color: #f39c12; font-weight: bold;">[Chorus]</span><br>
            [Natural Khmer Prose Line 1]<br>
        </div>
        """

        contents = [prompt]
        uploaded_media = None

        if media_filename:
            file_path = os.path.join(MEDIA_DIR, media_filename)
            if os.path.exists(file_path):
                uploaded_media = genai.upload_file(path=file_path)
                
                # 🎯 [ចំណុចសំខាន់បំផុត] ក្បួនរង់ចាំ Gemini អាន File អោយចប់សិន ទើបមិន Error
                while uploaded_media.state.name == "PROCESSING":
                    time.sleep(2)
                    uploaded_media = genai.get_file(uploaded_media.name)
                    
                if uploaded_media.state.name == "FAILED":
                    return jsonify({'error': "⚠️ AI មិនអាចអានឯកសារនេះបានទេ!"})
                    
                contents.append(uploaded_media)
        
        if text_content:
            contents.append(f"Here are the lyrics/text to translate:\n{text_content}")
        else:
            contents.append("Please listen to the attached audio/video, transcribe the lyrics with structure tags, and translate following the strict conceptual prose rules.")

        response = model.generate_content(contents)
        
        if uploaded_media: genai.delete_file(uploaded_media.name)

        result_text = response.text.replace("```html", "").replace("```", "").strip()
        return jsonify({'result_html': result_text})

    except Exception as e: 
        error_msg = str(e).lower()
        friendly_error = f"មានបញ្ហាបច្ចេកទេស: {str(e)}"
        if "quota" in error_msg or "429" in error_msg: friendly_error = "⚠️ អស់កូតាប្រើប្រាស់ហើយ!"
        elif "api_key" in error_msg or "400" in error_msg: friendly_error = "🔑 API Key មិនត្រឹមត្រូវ!"
        elif "timeout" in error_msg: friendly_error = "⏳ ម៉ាស៊ីនគិតយូរពេក (Timeout)។"
        return jsonify({'error': friendly_error})

# ----------------------------------------------------
# បើករត់ Server សម្រាប់ Cloud
# ----------------------------------------------------
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)