import webbrowser
from aerogen.server import run_server

def main():
    port = 8000
    print(f'Aerogen v2 — http://localhost:{port}')
    webbrowser.open(f'http://localhost:{port}')
    run_server(port)
if __name__ == '__main__':
    main()
