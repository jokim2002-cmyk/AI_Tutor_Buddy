import flet as ft

def main(page: ft.Page):
    page.title = "AI Tutor Buddy"
    page.window_width = 400
    page.window_height = 700
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.add(
        ft.Text("AI Tutor Buddy", size=30, weight=ft.FontWeight.BOLD, color="blue"),
        ft.Text("System Status: UI is Active!", size=15)
    )

if __name__ == '__main__':
    ft.app(target=main)
