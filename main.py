import flet as ft
from google import genai
import os
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

# We initialize the client outside the main function so Python 
# doesn't garbage collect it and close the HTTP connection!
api_key = os.getenv("GEMINI_API_KEY")
ai_client = genai.Client(api_key=api_key) if api_key else None

def main(page: ft.Page):
    if not ai_client:
        page.add(ft.Text("Error: API Key not found! Please check your .env file.", color="red"))
        return
    
    # Strict Teacher Persona
    system_instruction = '''You are a strict but friendly AI Tutor for 7th and 8th-grade English medium students in India. 
    Rule 1: Never give direct answers to homework or math problems.
    Rule 2: Explain concepts in simple language, then ask a guiding question to make the student think.
    Rule 3: Do not blindly agree. Verify the student's logic first.
    Rule 4: Keep responses concise and engaging.'''
    
    # Initialize Chat Session
    chat_session = ai_client.chats.create(
        model='gemini-2.5-flash',
        config={"system_instruction": system_instruction}
    )

    page.title = "AI Tutor Buddy"
    page.window_width = 400
    page.window_height = 700
    
    chat_history = ft.ListView(expand=True, spacing=10, auto_scroll=True)
    user_input = ft.TextField(hint_text="Ask your doubt here...", expand=True)
    
    def send_message(e):
        if user_input.value:
            user_text = user_input.value
            chat_history.controls.append(ft.Text(f"Student: {user_text}", color="blue", weight=ft.FontWeight.BOLD))
            user_input.value = ""
            page.update()
            
            try:
                response = chat_session.send_message(user_text)
                chat_history.controls.append(ft.Text(f"Tutor: {response.text}", color="green"))
            except Exception as ex:
                chat_history.controls.append(ft.Text(f"Error: {str(ex)}", color="red"))
            
            page.update()

    send_button = ft.ElevatedButton("Send", on_click=send_message)
    
    page.add(
        ft.Text("AI Tutor Buddy", size=24, weight=ft.FontWeight.BOLD, color="blue"),
        chat_history,
        ft.Row([user_input, send_button])
    )

if __name__ == '__main__':
    # Using ft.app(main) which works for this version. The warnings can be ignored.
    ft.app(main)
