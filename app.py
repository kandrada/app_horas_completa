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

# --- Función de Soporte (SIMPLIFICADA) ---
def obtener_saldo_horas(nombre_usuario):
    """Busca el saldo de horas *directamente* de la hoja 'Saldos'."""
    try:
        if sheet_saldos:
            registros = sheet_saldos.get_all_records()
            for r in registros:
                if r.get('Nombre') == nombre_usuario:
                    # Lee el valor actualizado de la columna 'Horas acumuladas'
                    return r.get('Horas acumuladas', 0) 
            return 0
        return 0
    except Exception as e:
        print(f"Error al obtener saldo para {nombre_usuario}: {e}")
        return 0

# --- Función de Soporte para actualizar Saldos ---
def actualizar_saldo(nombre_usuario, horas_a_restar):
    """Busca al usuario en 'Saldos' y resta la cantidad de horas."""
    try:
        if not sheet_saldos:
            print("Error: Hoja 'Saldos' no conectada.")
            return False

        # 1. Obtener todos los valores y encontrar la columna de Horas Acumuladas
        data = sheet_saldos.get_all_values()
        header = data[0]
        
        # Encontrar el índice de la columna 'Nombre' y 'Horas acumuladas'
        try:
            col_nombre = header.index('Nombre')
            col_horas = header.index('Horas acumuladas')
        except ValueError:
            print("Error: No se encontraron las columnas 'Nombre' u 'Horas acumuladas' en la hoja 'Saldos'.")
            return False

        # 2. Buscar al usuario y obtener su número de fila
        fila_usuario = -1
        horas_actuales = 0
        for i, row in enumerate(data[1:], start=2): # Empezamos en la fila 2
            if row and row[col_nombre] == nombre_usuario:
                fila_usuario = i
                # Intentar convertir el valor de horas a número (si no existe, usar 0)
                try:
                    horas_actuales = float(row[col_horas].replace(',', '.'))
                except (ValueError, IndexError):
                    horas_actuales = 0
                break

        if fila_usuario == -1:
            print(f"Error: Usuario {nombre_usuario} no encontrado en la hoja 'Saldos'.")
            return False

        # 3. Calcular y actualizar el nuevo saldo
        nuevo_saldo = max(0, horas_actuales - horas_a_restar)
        
        # El método update_cell necesita el número de fila (fila_usuario) y el número de columna (col_horas + 1)
        sheet_saldos.update_cell(fila_usuario, col_horas + 1, nuevo_saldo)
        return True

    except Exception as e:
        print(f"Error al actualizar saldo en Google Sheets: {e}")
        return False

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

# --- Vista gestor (MODIFICADA) ---
@app.route("/gestor", methods=["GET", "POST"])
def gestor():
    if "usuario" not in session or session["rol"] != "gestor":
        return redirect(url_for("login"))

    if request.method == "POST":
        fila_solicitud = int(request.form["fila"])
        accion = request.form["accion"]
        
        # 1. Leer los datos de la solicitud ANTES de actualizar el estado
        datos_solicitud = sheet_solicitudes.row_values(fila_solicitud)
        
        # Buscar el índice de las columnas necesarias
        header_solicitudes = sheet_solicitudes.row_values(1)
        
        try:
            # Asumimos que la hoja 'Solicitudes' tiene 'Nombre' y 'Cantidad de horas'
            idx_nombre = header_solicitudes.index("Nombre")
            idx_horas = header_solicitudes.index("Cantidad de horas")
            
            nombre_empleado = datos_solicitud[idx_nombre]
            horas_solicitadas = float(datos_solicitud[idx_horas])
            
        except (ValueError, IndexError):
            flash("Error al leer los datos de la solicitud. Verifique los encabezados.", "error")
            return redirect(url_for("gestor"))

        # 2. Actualizar el estado de la solicitud en la hoja 'Solicitudes'
        col_estado = header_solicitudes.index("Estado") + 1
        sheet_solicitudes.update_cell(fila_solicitud, col_estado, "Aprobado" if accion == "aprobar" else "Rechazado")
        
        # 3. Lógica CRÍTICA: Actualizar el Saldo si fue APROBADA
        if accion == "aprobar":
            if not actualizar_saldo(nombre_empleado, horas_solicitadas):
                flash(f"Error al restar {horas_solicitadas} horas del saldo de {nombre_empleado}.", "error")
            else:
                flash(f"Solicitud aprobada y {horas_solicitadas} horas restadas del saldo de {nombre_empleado}.", "success")
        else:
            flash("Solicitud rechazada.", "warning")

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





