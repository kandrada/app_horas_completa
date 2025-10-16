from flask import Flask, render_template, request, redirect, url_for, session, flash
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import os
import json 

app = Flask(__name__)
app.secret_key = "una_clave_segura_123"

# --- CONFIGURACIÓN GOOGLE SHEETS (MODIFICADA para Despliegue) ---
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

try:
    # 1. Intentar cargar las credenciales desde la Variable de Entorno
    creds_json = os.environ.get("GSPREAD_CREDENTIALS")
    
    # 2. Si la variable no existe en el servidor, no podemos continuar.
    if not creds_json:
        # En el servidor, si no encuentra la variable, asumimos que no hay credenciales
        # y lanzamos un error que no confunde al intérprete de Python.
        raise ValueError("La variable de entorno GSPREAD_CREDENTIALS no está configurada. El despliegue fallará.")

    # 3. Si la variable existe, la usamos para autorizar gspread
    creds_info = json.loads(creds_json)
    credentials = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    
    client = gspread.authorize(credentials)
    SPREADSHEET_NAME = "Prueba" 
    sheet_saldos = client.open(SPREADSHEET_NAME).worksheet("Saldos")
    sheet_solicitudes = client.open(SPREADSHEET_NAME).worksheet("Solicitudes")
    print("Conexión a Google Sheets exitosa.")


except Exception as e:
    # Este bloque maneja tanto el nuevo ValueError como cualquier error de conexión
    print(f"Error al conectar con Google Sheets: {e}")
    sheet_saldos = None
    sheet_solicitudes = None

# --- Función para obtener usuarios del Google Sheet ---
def get_usuarios_from_sheet():
    if sheet_saldos is None:
        return {}
    
    try:
        registros = sheet_saldos.get_all_records()
        usuarios_db = {}
        
        for r in registros:
            # Los nombres de las columnas deben ser exactamente 'Nombre', 'Password', 'Rol'
            usuario = r.get("Nombre") 
            password = r.get("Password") 
            rol = r.get("Rol", "empleado") 
            
            if usuario and password:
                # La clave del diccionario es el nombre de usuario (Nombre)
                usuarios_db[str(usuario)] = {"password": str(password), "rol": str(rol).lower()}
                
        return usuarios_db
    except Exception as e:
        print(f"Error al leer usuarios de Google Sheets: {e}")
        return {}

def obtener_saldo_horas(nombre_usuario):
    """Busca el saldo de horas acumuladas para un usuario en la hoja 'Saldos'."""
    try:
        if sheet_saldos:
            # Obtener todos los registros (la primera fila es la cabecera)
            registros = sheet_saldos.get_all_records()
            
            # Buscar el registro del usuario
            for r in registros:
                if r.get('Nombre') == nombre_usuario:
                    # 'Horas acumuladas' es el nombre de la columna en la hoja
                    return r.get('Horas acumuladas', 0) 
            return 0  # Si no encuentra el usuario, devuelve 0
        return 0
    except Exception as e:
        print(f"Error al obtener saldo para {nombre_usuario}: {e}")
        return 0

@app.route("/")
def home():
    if "usuario" in session:
        return redirect(url_for(session["rol"]))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    # Cargar usuarios dinámicamente
    USUARIOS_DB = get_usuarios_from_sheet() 

    if request.method == "POST":
        usuario = request.form["usuario"]
        password = request.form["password"]
        
        # Validación usando el diccionario dinámico
        if usuario in USUARIOS_DB and USUARIOS_DB[usuario]["password"] == password:
            session["usuario"] = usuario
            session["rol"] = USUARIOS_DB[usuario]["rol"]
            return redirect(url_for(session["rol"]))
        else:
            error = "Credenciales inválidas. Por favor, inténtalo de nuevo."
    
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# --- Vista empleado ---
@app.route("/empleado", methods=["GET", "POST"])
def empleado():
    if "usuario" not in session or session["rol"] != "empleado":
        return redirect(url_for("login"))

    if request.method == "POST":
        nombre = session["usuario"]
        fecha = request.form["fecha"]
        horas = request.form["horas"]
        motivo = request.form["motivo"]
        fecha_registro = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            # Añadir solicitud a la hoja 'Solicitudes'
            # (Asegúrate que el orden de tus columnas sea Nombre, Fecha solicitada, Cantidad de horas, Motivo, Estado, Fecha de registro)
            sheet_solicitudes.append_row([nombre, fecha, horas, motivo, fecha_registro , "Pendiente"])
            flash("Solicitud enviada para aprobación.", "success")
        except Exception as e:
            flash(f"Error al enviar solicitud: {e}", "error")

        return redirect(url_for("empleado"))
        
    horas_disponibles = obtener_saldo_horas(session["usuario"])
    
    # Mostrar solicitudes propias
    registros = sheet_solicitudes.get_all_records()
    mias = [r for r in registros if r["Nombre"] == session["usuario"]]

    return render_template("empleado.html", solicitudes=mias, nombre=session["usuario"], rol=session["rol"], saldo_horas=horas_disponibles)

# --- Vista gestor ---
@app.route("/gestor", methods=["GET", "POST"])
def gestor():
    if "usuario" not in session or session["rol"] != "gestor":
        return redirect(url_for("login"))

    if request.method == "POST":
        fila = int(request.form["fila"])
        accion = request.form["accion"]
        
        try:
            # El índice de la fila es 1-based en gspread.
            col_estado = sheet_solicitudes.row_values(1).index("Estado") + 1
            nuevo_estado = "Aprobado" if accion == "aprobar" else "Rechazado"
            sheet_solicitudes.update_cell(fila, col_estado, nuevo_estado)
            
            flash(f"Solicitud {fila-1} {nuevo_estado.lower()} con éxito.", "success")
        except Exception as e:
            flash(f"Error al procesar la solicitud: {e}", "error")

        return redirect(url_for("gestor"))

    registros = sheet_solicitudes.get_all_records()
    return render_template("gestor.html", solicitudes=registros, rol=session["rol"])

# --- Vista calendario ---
@app.route("/calendario")
def calendario():
    if "usuario" not in session:
        return redirect(url_for("login"))

    registros = sheet_solicitudes.get_all_records()
    
    # Crear un diccionario con fechas aprobadas y sus detalles
    solicitudes_aprobadas = {}
    for r in registros:
        # Aquí se usa 'Fecha solicitada' y 'Estado'
        if r["Estado"] == "Aprobado":
            fecha = r["Fecha solicitada"]
            if fecha not in solicitudes_aprobadas:
                solicitudes_aprobadas[fecha] = []
            solicitudes_aprobadas[fecha].append({
                'nombre': r['Nombre'],
                'horas': r['Cantidad de horas']
            })
    
    return render_template("calendario.html", 
                         solicitudes_aprobadas=solicitudes_aprobadas, 
                         rol=session.get("rol"))

# --- NUEVA RUTA: Agregar Usuario ---
@app.route("/agregar_usuario", methods=["GET", "POST"])
def agregar_usuario():
    # Solo permite que el gestor acceda a esta vista
    if "usuario" not in session or session["rol"] != "gestor":
        return redirect(url_for("login"))
    
    if request.method == "POST":
        nombre = request.form["nombre"].strip()
        password = request.form["password"]
        rol = request.form["rol"]
        saldo_inicial = request.form["saldo_inicial"]
        
        # Validar campos básicos
        if not nombre or not password:
            flash("Nombre y contraseña son obligatorios.", "error")
            return redirect(url_for("agregar_usuario"))

        # 1. Agregar el nuevo empleado a la hoja 'Saldos'
        try:
            encabezados_saldos = sheet_saldos.row_values(1)
            
            nueva_fila_dict = {
                "Nombre": nombre,
                "Password": password,
                "Rol": rol,
                "Horas acumuladas": saldo_inicial # Usamos Horas acumuladas según tu hoja
            }

            # Construir la fila asegurando el orden correcto de tu hoja
            nueva_fila = []
            for col in encabezados_saldos:
                # Agrega el valor si existe en el diccionario, sino, agrega un string vacío
                nueva_fila.append(nueva_fila_dict.get(col, ""))
            
            # Añadir la nueva fila
            sheet_saldos.append_row(nueva_fila)
            
            flash(f"Usuario {nombre} agregado exitosamente.", "success")
            return redirect(url_for("gestor"))
        
        except Exception as e:
            flash(f"Error al agregar el usuario a Google Sheets: {e}", "error")
            return redirect(url_for("agregar_usuario"))

    # Para el método GET, simplemente renderiza el formulario
    return render_template("agregar_usuario.html", rol=session["rol"])


if __name__ == "__main__":
    app.run(debug=True)




