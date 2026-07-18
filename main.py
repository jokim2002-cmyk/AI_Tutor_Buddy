import flet as ft
from google import genai
import os
from dotenv import load_dotenv
import warnings
import speech_recognition as sr
import pyttsx3

warnings.filterwarnings("ignore", category=DeprecationWarning)
load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
ai_client = genai.Client(api_key=api_key) if api_key else None

# Voice Engine Setup
tts_engine = pyttsx3.init()
tts_engine.setProperty('rate', 150) # Normal speaking speed

def main(page: ft.Page):
    if not ai_client:
        page.add(ft.Text("Error: API Key not found! Please check your .env file.", color="red"))
        return
    
    system_instruction = '''You are a strict but friendly AI Tutor for 7th and 8th-grade English medium students in India. 
    Rule 1: Never give direct answers to homework or math problems.
    Rule 2: Explain concepts in simple language, then ask a guiding question to make the student think.
    Rule 3: Do not blindly agree. Verify the student's logic first.
    Rule 4: Keep responses concise and engaging. 
    Rule 5: DO NOT use markdown, bold text, or asterisks like ** in your response, as it will be read aloud by a voice engine.'''
    
    chat_session = ai_client.chats.create(
        model="gemini-3.5-flash",
        config={"system_instruction": system_instruction}
    )

    page.title = "AI Tutor Buddy"
    page.window_width = 400
    page.window_height = 700
    
    chat_history = ft.ListView(expand=True, spacing=10, auto_scroll=True)
    user_input = ft.TextField(hint_text="Ask your doubt here or click Mic...", expand=True)
    
    def speak(text):
        tts_engine.say(text)
        tts_engine.runAndWait()

    def send_message(e):
        if user_input.value:
            user_text = user_input.value
            chat_history.controls.append(ft.Text(f"Student: {user_text}", color="blue", weight=ft.FontWeight.BOLD))
            user_input.value = ""
            page.update()
            
            try:
                response = chat_session.send_message(user_text)
                clean_text = response.text.replace('*', '')
                chat_history.controls.append(ft.Text(f"Tutor: {clean_text}", color="green"))
                page.update()
                speak(clean_text) # AI speaks the response
            except Exception as ex:
                chat_history.controls.append(ft.Text(f"Error: {str(ex)}", color="red"))
                page.update()

    def listen_audio(e):
        user_input.hint_text = "Listening... Speak now!"
        page.update()
        
        recognizer = sr.Recognizer()
        with sr.Microphone() as source:
            try:
                audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
                text = recognizer.recognize_google(audio)
                user_input.value = text
                user_input.hint_text = "Ask your doubt here or click Mic..."
                page.update()
                send_message(None) # Automatically send the recognized text
            except Exception:
                user_input.hint_text = "Voice not detected. Try again..."
                page.update()

    send_button = ft.ElevatedButton("Send", on_click=send_message)
    mic_button = ft.IconButton(icon=ft.icons.MIC, icon_color="blue", on_click=listen_audio)
    
    page.add(
        ft.Text("AI Tutor Buddy", size=24, weight=ft.FontWeight.BOLD, color="blue"),
        chat_history,
        ft.Row([user_input, mic_button, send_button])
    )

if __name__ == '__main__':
    ft.app(main)