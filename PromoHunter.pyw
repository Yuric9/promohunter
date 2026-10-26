"""
PromoHunter - inicializador com dois cliques (sem prompt de comando).

Funciona de dois jeitos:
- Como PromoHunter.exe (gerado pelo PyInstaller): já vem com tudo, o servidor roda
  dentro do próprio programa.
- Como PromoHunter.pyw (precisa de Python instalado): na primeira vez cria o ambiente
  virtual e instala as dependências; depois sobe a API num processo separado.

Nos dois casos abre o painel no navegador e mostra uma janelinha de controle.
Fechar a janelinha desliga o PromoHunter.
"""
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

CONGELADO = getattr(sys, "frozen", False)  # True quando roda como .exe
PASTA = Path(sys.executable).parent if CONGELADO else Path(__file__).resolve().parent
RECURSOS = Path(getattr(sys, "_MEIPASS", PASTA))  # arquivos embutidos no .exe
VENV = PASTA / ".venv"
ENV = PASTA / ".env"
LOG = PASTA / "promohunter.log"
PORTA = 8000
URL = f"http://127.0.0.1:{PORTA}"
WINDOWS = os.name == "nt"
SEM_JANELA = subprocess.CREATE_NO_WINDOW if WINDOWS else 0
CHAVE_PLACEHOLDER = "troque-por-uma-chave-secreta"


def python_do_venv() -> Path:
    return VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")


def python_base() -> str:
    """O python.exe (com console) ao lado do pythonw.exe que abriu este arquivo."""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe":
        exe = exe.with_name("python.exe")
    return str(exe)


def rodar(cmd, log):
    log.write(f"\n$ {' '.join(map(str, cmd))}\n")
    log.flush()
    subprocess.run(cmd, cwd=PASTA, stdout=log, stderr=subprocess.STDOUT, check=True, creationflags=SEM_JANELA)


def preparar(avisar):
    """Instala tudo que falta. Só demora na primeira execução."""
    with open(LOG, "a", encoding="utf-8") as log:
        if not python_do_venv().exists():
            avisar("Criando ambiente (só na primeira vez)...")
            rodar([python_base(), "-m", "venv", str(VENV)], log)
        marcador = VENV / ".instalado"
        reqs = PASTA / "requirements.txt"
        if not marcador.exists() or marcador.stat().st_mtime < reqs.stat().st_mtime:
            avisar("Instalando dependências (pode levar alguns minutos)...")
            rodar([str(python_do_venv()), "-m", "pip", "install", "-q", "-r", str(reqs)], log)
            marcador.touch()
    garantir_env()


def garantir_env():
    """Cria o .env a partir do exemplo e gera uma API_KEY aleatória se não houver."""
    if not ENV.exists():
        shutil.copy(RECURSOS / ".env.example", ENV)
    linhas = ENV.read_text(encoding="utf-8").splitlines()
    for i, linha in enumerate(linhas):
        if linha.startswith("API_KEY="):
            valor = linha.split("=", 1)[1].strip()
            if valor and valor != CHAVE_PLACEHOLDER:
                return
            linhas[i] = f"API_KEY={secrets.token_urlsafe(24)}"
            break
    else:
        linhas.append(f"API_KEY={secrets.token_urlsafe(24)}")
    ENV.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def ler_api_key() -> str:
    for linha in ENV.read_text(encoding="utf-8").splitlines():
        if linha.startswith("API_KEY="):
            return linha.split("=", 1)[1].strip()
    return ""


def api_respondendo() -> bool:
    try:
        with urllib.request.urlopen(URL + "/saude", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


class ServidorProcesso:
    """Modo .pyw: roda o uvicorn do ambiente virtual num processo sem janela."""

    def iniciar(self):
        log = open(LOG, "a", encoding="utf-8")
        self.processo = subprocess.Popen(
            [str(python_do_venv()), "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(PORTA)],
            cwd=PASTA, stdout=log, stderr=subprocess.STDOUT, creationflags=SEM_JANELA,
        )

    def vivo(self) -> bool:
        return self.processo.poll() is None

    def parar(self):
        if self.vivo():
            self.processo.terminate()
            try:
                self.processo.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.processo.kill()


class ServidorEmbutido:
    """Modo .exe: roda o uvicorn numa thread dentro do próprio programa."""

    def iniciar(self):
        import uvicorn
        from app.main import app  # importado só agora, depois que o .env existe

        self.servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORTA, log_config=None))
        self.thread = threading.Thread(target=self.servidor.run, daemon=True)
        self.thread.start()

    def vivo(self) -> bool:
        return self.thread.is_alive()

    def parar(self):
        self.servidor.should_exit = True
        self.thread.join(timeout=5)


def esperar_servidor(servidor, segundos=30) -> bool:
    fim = time.time() + segundos
    while time.time() < fim:
        if not servidor.vivo():
            return False
        if api_respondendo():
            return True
        time.sleep(0.5)
    return False


def abrir_painel():
    webbrowser.open(f"{URL}/#chave={ler_api_key()}")


def abrir_arquivo(caminho: Path):
    if WINDOWS:
        os.startfile(caminho)
    else:
        subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", str(caminho)])


# ---- Iniciar com o Windows ----------------------------------------------------

def atalho_inicializacao() -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs/Startup/PromoHunter.vbs"


def ativar_inicializacao(ativar: bool):
    atalho = atalho_inicializacao()
    if ativar:
        if CONGELADO:
            comando = f'"""{sys.executable}"""'
        else:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            comando = f'"""{pythonw}"" ""{Path(__file__).resolve()}"""'
        atalho.write_text(f'CreateObject("WScript.Shell").Run {comando}, 0\n', encoding="utf-8")
    elif atalho.exists():
        atalho.unlink()


# ---- Janela de controle ---------------------------------------------------------

def main():
    os.chdir(PASTA)  # o .env e a pasta data ficam ao lado do programa
    if CONGELADO:
        # Sem console, stdout/stderr não existem: manda tudo para o arquivo de log.
        sys.stdout = sys.stderr = open(LOG, "a", encoding="utf-8", buffering=1)
        sys.path.insert(0, str(RECURSOS))

    import tkinter as tk
    from tkinter import messagebox

    janela = tk.Tk()
    janela.title("PromoHunter")
    janela.geometry("340x230")
    janela.resizable(False, False)

    tk.Label(janela, text="🔥 PromoHunter", font=("Segoe UI", 16, "bold")).pack(pady=(16, 4))
    status = tk.Label(janela, text="Preparando...", font=("Segoe UI", 10))
    status.pack()
    botoes = tk.Frame(janela)
    botoes.pack(pady=12)

    estado = {"servidor": None}

    def avisar(texto):
        janela.after(0, lambda: status.config(text=texto))

    def desligar():
        if estado["servidor"]:
            estado["servidor"].parar()
        janela.destroy()

    def pronto():
        status.config(text=f"✅ Rodando em {URL}", fg="green")
        tk.Button(botoes, text="Abrir painel", width=14, command=abrir_painel).grid(row=0, column=0, padx=4)
        tk.Button(botoes, text="Configurações", width=14, command=lambda: abrir_arquivo(ENV)).grid(row=0, column=1, padx=4)
        tk.Button(botoes, text="Ver log", width=14, command=lambda: abrir_arquivo(LOG)).grid(row=1, column=0, padx=4, pady=6)
        tk.Button(botoes, text="Desligar", width=14, command=desligar).grid(row=1, column=1, padx=4, pady=6)
        if WINDOWS:
            auto = tk.BooleanVar(value=atalho_inicializacao().exists())
            tk.Checkbutton(janela, text="Iniciar junto com o Windows", variable=auto,
                           command=lambda: ativar_inicializacao(auto.get())).pack()
        abrir_painel()

    def falhou(msg):
        status.config(text="❌ Não foi possível iniciar", fg="red")
        messagebox.showerror("PromoHunter", f"{msg}\n\nDetalhes em:\n{LOG}")
        tk.Button(botoes, text="Ver log", width=14, command=lambda: abrir_arquivo(LOG)).pack()

    def trabalho():
        try:
            if api_respondendo():
                janela.after(0, lambda: status.config(text="Já estava rodando"))
                janela.after(0, abrir_painel)
                janela.after(1500, janela.destroy)
                return
            if CONGELADO:
                garantir_env()
                servidor = ServidorEmbutido()
            else:
                preparar(avisar)
                servidor = ServidorProcesso()
            avisar("Iniciando servidor...")
            servidor.iniciar()
            estado["servidor"] = servidor
            if esperar_servidor(servidor):
                janela.after(0, pronto)
            else:
                janela.after(0, lambda: falhou("O servidor não respondeu. A porta 8000 pode estar em uso."))
        except subprocess.CalledProcessError:
            janela.after(0, lambda: falhou("Falha ao instalar as dependências. Verifique sua internet."))
        except Exception as e:
            janela.after(0, lambda: falhou(str(e)))

    janela.protocol("WM_DELETE_WINDOW", desligar)
    threading.Thread(target=trabalho, daemon=True).start()
    janela.mainloop()


if __name__ == "__main__":
    main()
