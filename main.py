import flet as ft

def main(page: ft.Page):
    page.title = "AI Tutor Buddy"
    page.window_width = 400
    page.window_height = 700
    
    # Chat display area
    chat_history = ft.ListView(expand=True, spacing=10, auto_scroll=True)
    
    # Input area
    user_input = ft.TextField(hint_text="Ask your doubt here...", expand=True)
    
    def send_message(e):
        if user_input.value:
            # Show student message
            chat_history.controls.append(ft.Text(f"Student: {user_input.value}", color="blue", weight=ft.FontWeight.BOLD))
            
            # Temporary AI dummy response
            chat_history.controls.append(ft.Text("Tutor: Let me think about that... (AI logic coming soon!)", color="green"))
            
            # Clear input box
            user_input.value = ""
            page.update()

    send_button = ft.ElevatedButton("Send", on_click=send_message)
    
    # Add all elements to the screen
    page.add(
        ft.Text("AI Tutor Buddy", size=24, weight=ft.FontWeight.BOLD, color="blue"),
        chat_history,
        ft.Row([user_input, send_button])
    )

if __name__ == '__main__':
    ft.app(target=main)
