from unicodedata import category
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import subprocess
import json
import re
import os
from unidecode import unidecode
from deep_translator import GoogleTranslator
import requests
from requests.auth import HTTPBasicAuth
from openai import OpenAI

app = Flask(__name__)

import os

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

user_language = None

def clean_transcription(text):
    return re.sub(r'\[.*?-->\s*.*?\]', '', text).strip()

def extract_alphanum(text):
    alphanum = re.findall(r'[A-Za-z0-9]+', text)
    return ''.join(alphanum).upper() if alphanum else None

def words_to_number(text, language="tr"):
    digits_map = {
        "tr": {
            "sıfır": "0", "bir": "1", "iki": "2", "üç": "3", "dört": "4",
            "beş": "5", "altı": "6", "yedi": "7", "sekiz": "8", "dokuz": "9"
        },
        "en": {
            "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
            "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"
        },
        "fr": {
            "zéro": "0", "un": "1", "deux": "2", "trois": "3", "quatre": "4",
            "cinq": "5", "six": "6", "sept": "7", "huit": "8", "neuf": "9"
        },
        "es": {
            "cero": "0", "uno": "1", "dos": "2", "tres": "3", "cuatro": "4",
            "cinco": "5", "seis": "6", "siete": "7", "ocho": "8", "nueve": "9"
        }
    }
    words = text.lower().replace(",", "").split()
    result = "".join(digits_map.get(language, {}).get(word, "") for word in words)
    return result if result else None

def run_whisper(audio_path, language="tr"):
    exe_path = r'C:\Users\DOF-Guest\whisper.cpp\build\bin\Release\whisper-cli.exe'
    model_path = r'C:\Users\DOF-Guest\whisper.cpp\ggml-base.bin'
    cmd = [exe_path, '-m', model_path, '-f', audio_path, '--language', language]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        return result.stdout.decode('utf-8', errors='replace').strip()
    except subprocess.CalledProcessError as e:
        print("Whisper hatası:", e)
        print("stderr:", e.stderr.decode('utf-8', errors='replace'))
        return ""

def search_error(query, error_list):
    if not query:
        return None
    query = unidecode(query).strip().lower()
    for err in error_list:
        if query == str(err.get("error_code", "")).lower():
            return err
    return None

def translate_text(text, target_lang="tr"):
    if not text or target_lang == "en":
        return text
    try:
        if isinstance(text, list):
            text = "\n".join(text)
        return GoogleTranslator(source='en', target=target_lang).translate(text)
    except Exception as e:
        print(f"Çeviri hatası: {e}")
        if isinstance(text, list):
            text = "\n".join(text)
        return text + " (Çeviri başarısız)"

def generate_ai_suggestions(error_code, error_data, user_language="en"):
    system_prompt = "You are an expert technical assistant."
    user_prompt = (
        f"Here is an error code and its details:\n"
        f"Error Code: {error_code}\n"
        f"Category: {error_data.get('category')}\n"
        f"Title: {error_data.get('title')}\n"
        f"Cause: {error_data.get('cause')}\n"
        f"Solution: {error_data.get('solution')}\n\n"
        "Please provide additional suggestions or explanations about what else can be done."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=300,
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print("OpenAI öneri hatası:", e)
        return "(AI önerisi alınamadı)"

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    global user_language
    incoming_msg = request.values.get("Body", "").strip()
    media_url = request.values.get("MediaUrl0")
    msg = MessagingResponse()

    if not user_language:
        if incoming_msg.lower().startswith(("en:", "en")):
            user_language = "en"
            incoming_msg = incoming_msg[3:].strip()
            msg.message("✅ Language selected: English")
        elif incoming_msg.lower().startswith(("tr:", "tr")):
            user_language = "tr"
            incoming_msg = incoming_msg[3:].strip()
            msg.message("✅ Dil seçildi: Türkçe")
        elif incoming_msg.lower().startswith(("fr:", "fr")):
            user_language = "fr"
            incoming_msg = incoming_msg[3:].strip()
            msg.message("✅ Langue sélectionnée : Français")
        elif incoming_msg.lower().startswith(("es:", "es")):
            user_language = "es"
            incoming_msg = incoming_msg[3:].strip()
            msg.message("✅ Idioma seleccionado: Español")
        else:
            user_language = "en"
            msg.message("✅ Default language selected: English")

    transcription = incoming_msg

    if media_url:
        media_content_type = request.values.get("MediaContentType0") or "audio/ogg"
        ext = media_content_type.split('/')[-1]
        audio_path_original = f"incoming.{ext}"
        audio_path_converted = "incoming.wav"

        try:
            r = requests.get(media_url, auth=HTTPBasicAuth(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
            r.raise_for_status()
            with open(audio_path_original, "wb") as f:
                f.write(r.content)
            print(f"Dosya '{audio_path_original}' indirildi.")
        except Exception as e:
            msg.message(f"Dosya indirilemedi: {e}")
            return str(msg)

        if os.path.getsize(audio_path_original) == 0:
            transcription = ""
        else:
            if ext != "wav":
                subprocess.run([
                    r"C:\Users\DOF-Guest\Downloads\ffmpeg-7.1.1-essentials_build\ffmpeg-7.1.1-essentials_build\bin\ffmpeg.exe",
                    "-y", "-i", audio_path_original, audio_path_converted
                ], check=True)
                transcription = run_whisper(audio_path_converted, user_language)
            else:
                transcription = run_whisper(audio_path_original, user_language)

    transcription = clean_transcription(transcription)
    print("Transkript:", transcription)

    error_code = extract_alphanum(transcription)
    if not error_code:
        clean_txt = re.sub(r'[^\w\s]', '', transcription.lower())
        error_code = words_to_number(clean_txt, user_language)
    if not error_code:
        error_code = transcription.lower()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(base_dir, "error.json")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            errors = json.load(f).get("errors", [])
    except Exception as e:
        msg.message(f"JSON yüklenemedi: {e}")
        return str(msg)

    result = search_error(error_code, errors)

    if result:
        category = result.get('category')
        title = result.get('title')
        cause = result.get('cause')
        solution = result.get('solution')

        ai_text = generate_ai_suggestions(error_code, result, user_language)

        if user_language == "tr":
            category = translate_text(category, "tr")
            title = translate_text(title, "tr")
            cause = translate_text(cause, "tr")
            solution = translate_text(solution, "tr")
            ai_text = translate_text(ai_text, "tr")
            reply_text = (
                f"Hata Kodu: {result.get('error_code')}\n"
                f"Kategori: {category}\n"
                f"Başlık: {title}\n"
                f"Sebep: {cause}\n"
                f"Çözüm: {solution}\n\n"
                f"Ek Öneriler:\n{ai_text}"
            )
        elif user_language == "fr":
            category = translate_text(category, "fr")
            title = translate_text(title, "fr")
            cause = translate_text(cause, "fr")
            solution = translate_text(solution, "fr")
            ai_text = translate_text(ai_text, "fr")
            reply_text = (
                f"Code d'erreur: {result.get('error_code')}\n"
                f"Catégorie: {category}\n"
                f"Titre: {title}\n"
                f"Cause: {cause}\n"
                f"Solution: {solution}\n\n"
                f"Suggestions supplémentaires:\n{ai_text}"
            )
        elif user_language == "es":
            category = translate_text(category, "es")
            title = translate_text(title, "es")
            cause = translate_text(cause, "es")
            solution = translate_text(solution, "es")
            ai_text = translate_text(ai_text, "es")
            reply_text = (
                f"Código de error: {result.get('error_code')}\n"
                f"Categoría: {category}\n"
                f"Título: {title}\n"
                f"Causa: {cause}\n"
                f"Solución: {solution}\n\n"
                f"Sugerencias adicionales:\n{ai_text}"
            )
        else:
            reply_text = (
                f"Error Code: {result.get('error_code')}\n"
                f"Category: {category}\n"
                f"Title: {title}\n"
                f"Cause: {cause}\n"
                f"Solution: {solution}\n\n"
                f"Additional Suggestions:\n{ai_text}"
            )
        msg.message(reply_text)
    else:
        if user_language == "tr":
            msg.message("❌ Hata bulunamadı. Lütfen geçerli bir hata kodu gönderin.")
        elif user_language == "fr":
            msg.message("❌ Erreur introuvable. Veuillez envoyer un code d'erreur valide.")
        elif user_language == "es":
            msg.message("❌ Error no encontrado. Por favor envíe un código de error válido.")
        else:
            msg.message("❌ Error not found. Please send a valid error code.")

    return str(msg)

if __name__ == "__main__":
    app.run(port=5000, debug=True)
