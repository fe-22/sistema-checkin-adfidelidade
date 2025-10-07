import os
import datetime
import time
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import create_engine, text
from sqlalchemy.sql import text
import pandas as pd

# ------------------ Configuração Flask ------------------
app = Flask(__name__)
app.secret_key = 'chave-secreta-assembleia-deus-fidelidade-2024'

# ------------------ Configuração do Banco ------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./test.db")

# Ajuste necessário para Postgres no Render/Railway
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://")

# Configuração engine dependendo do banco
if "sqlite" in DATABASE_URL:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    print("✅ Usando SQLite para desenvolvimento local")
else:
    engine = create_engine(DATABASE_URL)
    print("✅ Usando PostgreSQL")

# ------------------ Funções auxiliares ------------------
def init_db():
    """Cria as tabelas necessárias."""
    max_retries = 3
    retry_delay = 2  # segundos
    
    for attempt in range(max_retries):
        try:
            with engine.begin() as conn:
                # Tabela de usuários (líderes)
                conn.execute(text("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    senha TEXT NOT NULL,
                    tipo TEXT DEFAULT 'lider',
                    criado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """))
                
                # Tabela de membros (obreiros)
                conn.execute(text("""
                CREATE TABLE IF NOT EXISTS membros (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL,
                    grupo TEXT,
                    telefone TEXT,
                    email TEXT,
                    observacoes TEXT,
                    presente BOOLEAN DEFAULT FALSE,
                    data_checkin TIMESTAMP,
                    checkin_latitude REAL,
                    checkin_longitude REAL,
                    criado TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """))

                # Tabela de atas (para registros de reuniões)
                conn.execute(text("""
                CREATE TABLE IF NOT EXISTS atas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_reuniao DATE NOT NULL,
                    tipo TEXT,           -- Ex: Culto de Obreiros, Reunião de Líderes
                    departamento TEXT,   -- Ex: Evangelismo, Louvor, Intercessão
                    tema TEXT,
                    local TEXT,
                    observacoes TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """))
                
                # Usuário líder padrão
                result = conn.execute(text("SELECT COUNT(*) FROM usuarios")).scalar()
                if result == 0:
                    senha_hash = generate_password_hash("admin123")
                    conn.execute(
                        text("INSERT INTO usuarios (nome, email, senha, tipo) VALUES (:n, :e, :s, :t)"),
                        {"n": "Pastor Líder", "e": "lider@adfidelidade.com", "s": senha_hash, "t": "lider"}
                    )
                    print("✅ Usuário líder criado: lider@adfidelidade.com / admin123")
                
                # Membros de exemplo
                result = conn.execute(text("SELECT COUNT(*) FROM membros")).scalar()
                if result == 0:
                    conn.execute(text("""
                    INSERT INTO membros (nome, grupo, telefone) VALUES 
                    ('Fernando Alexandre Fernandes', 'Evangelismo', '(11) 99999-9999'),
                    ('Maria Silva Santos', 'Louvor', '(11) 98888-8888'),
                    ('João Pereira Oliveira', 'Intercessão', '(11) 97777-7777')
                    """))
                    print("✅ Dados de exemplo inseridos")
                    
            print("✅ Banco de dados inicializado com sucesso!")
            break
            
        except Exception as e:
            print(f"❌ Tentativa {attempt + 1} falhou: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
            else:
                print("❌ Falha ao inicializar banco de dados após várias tentativas")

    # Migração simples: garantir colunas de geolocalização em membros (idempotente)
    try:
        with engine.begin() as conn:
            cols = conn.execute(text("PRAGMA table_info(membros)")).fetchall()
            col_names = {c[1] for c in cols}
            if "checkin_latitude" not in col_names:
                conn.execute(text("ALTER TABLE membros ADD COLUMN checkin_latitude REAL"))
            if "checkin_longitude" not in col_names:
                conn.execute(text("ALTER TABLE membros ADD COLUMN checkin_longitude REAL"))
    except Exception:
        # Ignorar falhas de migração silenciosamente para compatibilidade
        pass

# ------------------ FORÇAR INICIALIZAÇÃO DO BANCO ------------------
init_db()

# ------------------ Rotas Públicas (Obreiros) ------------------
@app.route("/checkin_obreiro", methods=["POST"])
def checkin_obreiro():
    nome = request.form["nome"]
    grupo = request.form["grupo"]
    lat = request.form.get("latitude")
    lon = request.form.get("longitude")
    
    try:
        with engine.begin() as conn:
            result = conn.execute(
                text("SELECT id FROM membros WHERE nome = :n AND grupo = :g"),
                {"n": nome, "g": grupo}
            ).fetchone()
            
            if result:
                conn.execute(
                    text("UPDATE membros SET presente = TRUE, data_checkin = :d, checkin_latitude = :lat, checkin_longitude = :lon WHERE id = :id"),
                    {"d": datetime.datetime.now(), "id": result.id, "lat": float(lat) if lat else None, "lon": float(lon) if lon else None}
                )
                flash("Check-in realizado com sucesso! Deus te abençoe!", "success")
            else:
                flash("Obreiro não encontrado. Verifique nome e grupo.", "warning")
    except Exception as e:
        flash(f"Erro ao realizar check-in: {e}", "danger")
    
    return redirect(url_for("index"))

@app.route("/")
def index():
    return render_template("index.html")

# ------------------ Rotas de Liderança (Protegidas) ------------------
@app.route("/login_lider")
def login_lider():
    return render_template("login_lider.html")

@app.route("/auth_lider", methods=["POST"])
def auth_lider():
    email = request.form["email"]
    senha = request.form["senha"]

    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT * FROM usuarios WHERE email = :e AND tipo = 'lider'"), 
                {"e": email}
            ).mappings().fetchone()

        if result and check_password_hash(result["senha"], senha):
            session["usuario_id"] = result["id"]
            session["usuario_nome"] = result["nome"]
            session["tipo_usuario"] = "lider"
            flash("Login bem-sucedido!", "success")
            return redirect(url_for("painel_lider"))
        else:
            flash("Credenciais inválidas ou acesso não autorizado", "danger")
            return redirect(url_for("login_lider"))
    except Exception as e:
        flash(f"Erro no login: {e}", "danger")
        return redirect(url_for("login_lider"))

@app.route("/painel_lider")
def painel_lider():
    if "tipo_usuario" not in session or session["tipo_usuario"] != "lider":
        flash("Acesso restrito para líderes. Faça login primeiro.", "warning")
        return redirect(url_for("login_lider"))

    try:
        with engine.connect() as conn:
            membros = conn.execute(
                text("SELECT * FROM membros ORDER BY nome")
            ).mappings().all()
            
            total_presentes = conn.execute(
                text("SELECT COUNT(*) FROM membros WHERE presente = TRUE")
            ).scalar() or 0
            
            total_ausentes = conn.execute(
                text("SELECT COUNT(*) FROM membros WHERE presente = FALSE")
            ).scalar() or 0
            
            total_membros = conn.execute(
                text("SELECT COUNT(*) FROM membros")
            ).scalar() or 0
            
        return render_template("painel_lider.html", 
                             membros=membros,
                             total_presentes=total_presentes,
                             total_ausentes=total_ausentes,
                             total_membros=total_membros)
    except Exception as e:
        flash(f"Erro ao carregar painel: {e}", "danger")
        return redirect(url_for("login_lider"))

@app.route("/checkin_lider", methods=["POST"])
def checkin_lider():
    if "tipo_usuario" not in session or session["tipo_usuario"] != "lider":
        flash("Acesso não autorizado", "danger")
        return redirect(url_for("login_lider"))
    
    membro_id = request.form["membro_id"]
    presente = request.form.get("presente") == "on"

    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE membros SET presente = :p, data_checkin = :d WHERE id = :id"),
                {"p": presente, "d": datetime.datetime.now() if presente else None, "id": membro_id}
            )
        flash("Check-in atualizado com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao atualizar check-in: {e}", "danger")
    
    return redirect(url_for("painel_lider"))

@app.route("/cadastrar_obreiro", methods=["POST"])
def cadastrar_obreiro():
    if "tipo_usuario" not in session or session["tipo_usuario"] != "lider":
        flash("Acesso não autorizado", "danger")
        return redirect(url_for("login_lider"))
    
    nome = request.form["nome"]
    grupo = request.form["grupo"]
    telefone = request.form.get("telefone", "")
    email = request.form.get("email", "")

    try:
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO membros (nome, grupo, telefone, email) VALUES (:n, :g, :t, :e)"),
                {"n": nome, "g": grupo, "t": telefone, "e": email}
            )
        flash("Obreiro cadastrado com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao cadastrar obreiro: {e}", "danger")
    
    return redirect(url_for("painel_lider"))

# ------------------ Excel: Download modelo e Upload em lote ------------------
@app.route("/download_modelo_obreiro")
def download_modelo_obreiro():
    if "tipo_usuario" not in session or session.get("tipo_usuario") != "lider":
        flash("Acesso não autorizado", "danger")
        return redirect(url_for("login_lider"))

    df = pd.DataFrame({
        "nome": ["Ex: João da Silva"],
        "grupo": ["Ex: Evangelismo"],
        "telefone": ["(11) 99999-9999"],
        "email": ["joao@email.com"]
    })
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="obreiros")
    output.seek(0)
    return send_file(output, as_attachment=True, download_name="modelo_obreiros.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/upload_obreiros", methods=["POST"])
def upload_obreiros():
    if "tipo_usuario" not in session or session.get("tipo_usuario") != "lider":
        flash("Acesso não autorizado", "danger")
        return redirect(url_for("login_lider"))

    file = request.files.get("arquivo")
    if not file:
        flash("Nenhum arquivo enviado", "warning")
        return redirect(url_for("painel_lider"))

    try:
        df = pd.read_excel(file)
        # Normalizar colunas esperadas
        expected_cols = {"nome", "grupo", "telefone", "email"}
        df_cols = {c.strip().lower() for c in df.columns}
        if not expected_cols.issubset(df_cols):
            flash("Modelo inválido. Certifique-se de usar o arquivo modelo.", "danger")
            return redirect(url_for("painel_lider"))

        # Renomear para padrão
        rename_map = {c: c.strip().lower() for c in df.columns}
        df = df.rename(columns=rename_map)
        df = df[list(expected_cols)]

        registros = df.fillna("").to_dict(orient="records")
        inseridos = 0
        with engine.begin() as conn:
            for r in registros:
                if not r.get("nome"):
                    continue
                conn.execute(
                    text("INSERT INTO membros (nome, grupo, telefone, email) VALUES (:n, :g, :t, :e)"),
                    {"n": r.get("nome"), "g": r.get("grupo"), "t": r.get("telefone"), "e": r.get("email")}
                )
                inseridos += 1
        flash(f"Upload concluído. {inseridos} obreiros adicionados.", "success")
    except Exception as e:
        flash(f"Erro ao processar arquivo: {e}", "danger")
    return redirect(url_for("painel_lider"))


# ------------------ Rotas da Ata ------------------
@app.route("/ata", methods=["GET"]) 
def form_ata():
    if "tipo_usuario" not in session or session.get("tipo_usuario") != "lider":
        flash("Acesso não autorizado", "danger")
        return redirect(url_for("login_lider"))
    # Opções para combos
    tipos = ["Culto de Obreiros", "Reunião de Líderes", "Assembleia", "Treinamento"]
    departamentos = ["Evangelismo", "Louvor", "Intercessão", "Diaconato", "Ensino"]
    return render_template("ata.html", tipos=tipos, departamentos=departamentos)


@app.route("/ata", methods=["POST"]) 
def salvar_ata():
    if "tipo_usuario" not in session or session.get("tipo_usuario") != "lider":
        flash("Acesso não autorizado", "danger")
        return redirect(url_for("login_lider"))

    data_reuniao = request.form.get("data_reuniao")
    tipo = request.form.get("tipo")
    departamento = request.form.get("departamento")
    tema = request.form.get("tema")
    local = request.form.get("local")
    observacoes = request.form.get("observacoes")

    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO atas (data_reuniao, tipo, departamento, tema, local, observacoes)
                    VALUES (:data_reuniao, :tipo, :departamento, :tema, :local, :observacoes)
                """),
                {
                    "data_reuniao": data_reuniao,
                    "tipo": tipo,
                    "departamento": departamento,
                    "tema": tema,
                    "local": local,
                    "observacoes": observacoes
                }
            )
        flash("Ata registrada com sucesso!", "success")
        return redirect(url_for("form_ata"))
    except Exception as e:
        flash(f"Erro ao salvar ata: {e}", "danger")
        return redirect(url_for("form_ata"))

@app.route("/remover_obreiro/<int:id>", methods=["POST"])
def remover_obreiro(id):
    if "tipo_usuario" not in session or session["tipo_usuario"] != "lider":
        flash("Acesso não autorizado", "danger")
        return redirect(url_for("login_lider"))
    
    try:
        with engine.begin() as conn:
            conn.execute(
                text("DELETE FROM membros WHERE id = :id"),
                {"id": id}
            )
        flash("Obreiro removido com sucesso!", "success")
    except Exception as e:
        flash(f"Erro ao remover obreiro: {e}", "danger")
    
    return redirect(url_for("painel_lider"))

@app.route("/logout")
def logout():
    session.clear()
    flash("Logout realizado com sucesso.", "info")
    return redirect(url_for("index"))

# ------------------ Inicialização ------------------
if __name__ == "__main__":
    port = 5000
    print(f"🚀 Servidor iniciado em http://localhost:{port}")
    print("📋 Acesso para obreiros: http://localhost:5000")
    print("🔐 Acesso para líderes: http://localhost:5000/login_lider")
    print("👤 Login líder: lider@adfidelidade.com / admin123")
    app.run(host="0.0.0.0", port=port, debug=True)