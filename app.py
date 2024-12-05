# app.py

from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify
from netmiko import ConnectHandler
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import json
import os
import logging
from logging.handlers import RotatingFileHandler
from nornir import InitNornir
from nornir.core.exceptions import NornirExecutionError
from nornir_utils.plugins.functions import print_result
from nornir_netmiko.tasks import netmiko_send_config, netmiko_save_config,netmiko_send_command
from nornir.core.filter import F

app = Flask(__name__)

# Inicializador Nornir
nr = InitNornir(config_file="config.yml")


# Obtener los nombres de los hosts del inventario
def obtener_hosts():
    return list(nr.inventory.hosts.keys())

app = Flask(__name__)
app.config.from_pyfile('config.py')  

# Configurar logging
if not os.path.exists('logs'):
    os.makedirs('logs')

handler = RotatingFileHandler('logs/app.log', maxBytes=100000, backupCount=3)
handler.setLevel(logging.DEBUG)  # Cambiar a DEBUG para capturar todos los logs
formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
handler.setFormatter(formatter)
app.logger.addHandler(handler)

app.logger.setLevel(logging.DEBUG)  # Cambiar a DEBUG
app.logger.info('Aplicación iniciada')

# Configurar Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Nombre de la función de vista para la página de login

# Clase de Usuario Ficticio
class User(UserMixin):
    def __init__(self, id):
        self.id = id

# Cargar usuarios desde un archivo JSON o base de datos (simplificado aquí)
USERS = {'admin': {'password': 'password'}}  # Reemplaza con una fuente de usuarios más segura en producción

@login_manager.user_loader
def load_user(user_id):
    return User(user_id)


# Ruta de inicio de sesión
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = USERS.get(username)
        if user and user['password'] == password:
            user_obj = User(id=username)
            login_user(user_obj)
            flash('Has iniciado sesión correctamente.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Credenciales inválidas.', 'danger')
            return redirect(url_for('login'))
    return render_template('login.html')

# Ruta de cierre de sesión
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Has cerrado sesión.', 'info')
    return redirect(url_for('login'))

# Cargar la lista de switches
with open(app.config['SWITCHES_FILE']) as f:
    switches = json.load(f)
    
@app.route('/get_switches')
@login_required
def get_switches():
    """Devuelve el listado de switches."""
    sw = [host.name for host in nr.inventory.hosts.values()]
    return jsonify(sw)

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/get_ports/<switch_name>', methods=['GET'])
@login_required
def get_ports(switch_name):
    # Asumiendo que los puertos están en el inventario o se obtienen dinámicamente
    device = nr.inventory.hosts.get(switch_name)
    if not device:
        return jsonify({"error": "Switch no encontrado"}), 404

    # Puertos de ejemplo
    ports = ['Ethernet0/0', 'Ethernet0/1', 'Ethernet0/2', 'Ethernet0/3']
    return jsonify({"ports": ports})


@app.route('/vlans')
@login_required
def vlans():
    vlan_info = []
    for switch in switches:
        try:
            net_connect = ConnectHandler(**switch)
            net_connect.enable()
            output = net_connect.send_command('show vlan brief')
            vlan_info.append({'host': switch['host'], 'output': output})
            net_connect.disconnect()
        except Exception as e:
            vlan_info.append({'host': switch['host'], 'output': f'Error: {e}'})
            app.logger.error(f"Error al obtener VLANs de {switch['host']}: {e}")
    return render_template('vlans.html', vlan_info=vlan_info)


@app.route('/get_vlan', methods=['POST'])
@login_required
def get_vlan():
    # Obtiene los datos enviados por el cliente
    data = request.get_json()
    
    # Verifica si los datos fueron recibidos correctamente
    swit = data.get('switch')
    vlan_info = []

    # Filtra el inventario de Nornir para el switch especificado
    filtered_nr = nr.filter(name=swit)

    # Verifica si el switch existe en el inventario
    if not filtered_nr.inventory.hosts:
        return jsonify({"error": f"Switch '{swit}' no encontrado en el inventario"}), 404

    try:
        # Ejecuta la tarea en el switch filtrado
        result = filtered_nr.run(
            task=netmiko_send_command,
            command_string="show vlan brief"
        )
           
        # Procesa el resultado
        if swit in result:
            # Accede al MultiResult de este switch
            multi_result = result[swit]

            # Accede a la salida del primer Result (suponiendo que hay al menos uno)
            if multi_result:
                vlan_output = multi_result[0].result
                vlan_info.append({'host': swit, 'output': vlan_output})
            else:
                vlan_info.append({'host': swit, 'output': 'No hay resultados en el comando.'})

        else:
            vlan_info.append({'host': swit, 'output': 'Switch no encontrado en los resultados.'})

    except Exception as e:
        vlan_info.append({'host': swit, 'output': f'Error: {e}'})
        app.logger.error(f"Error al obtener VLANs de {swit}: {e}")

    return jsonify({'vlan_html': render_template('vlans2.html', vlan_info=vlan_info)})




@app.route('/add_vlan', methods=['GET', 'POST'])
@login_required
def add_vlan():
    if request.method == 'POST':
        # Datos del formulario
        vlan_id = request.form['vlan_id'].strip()
        vlan_name = request.form['vlan_name'].strip()
        switch_name = request.form['switch'].strip()

        # Validaciones básicas
        if not vlan_id.isdigit():
            flash('El ID de VLAN debe ser un número.', 'danger')
            return redirect(url_for('add_vlan'))

        # Filtrar switch en el inventario de Nornir
        filtered_nr = nr.filter(name=switch_name)
        


        # Comandos para configurar la VLAN
        commands = [f'vlan {vlan_id}', f'name {vlan_name}']

        try:
            # Ejecutar comandos en el switch
            result= filtered_nr.run(
                task=netmiko_send_config,
                config_commands=commands
            )
            print_result(result)

            # Verificar resultado
            if result.failed:
                flash(f"Error al configurar VLAN en {switch_name}.", 'danger')
            else:
                flash(f"VLAN {vlan_id} - {vlan_name} agregada en {switch_name}.", 'success')

        except Exception as e:
            app.logger.error(f"Error al agregar VLAN en {switch_name}: {e}")
            flash(f"Error: {e}", 'danger')

        return redirect(url_for('add_vlan'))

    # GET request: renderizar el formulario
    return render_template('add_vlan.html')

@app.route('/assign_vlan', methods=['GET', 'POST'])
@login_required
def assign_vlan():
    if request.method == 'POST':
        # Datos del formulario
        vlan_id = request.form['vlan_id'].strip()
        port = request.form['port'].strip()
        switch_name = request.form['switch'].strip()

        # Validaciones básicas
        if not vlan_id.isdigit():
            flash('El ID de VLAN debe ser un número.', 'danger')
            return redirect(url_for('assign_vlan'))

        if not port:
            flash('El puerto no puede estar vacío.', 'danger')
            return redirect(url_for('assign_vlan'))

        if not switch_name:
            flash('Debes seleccionar un switch.', 'danger')
            return redirect(url_for('assign_vlan'))

        # el switch en el inventario de Nornir
        filtered_nr = nr.filter(name=switch_name)

        if not filtered_nr.inventory.hosts:
            flash('Switch no encontrado.', 'danger')
            return redirect(url_for('assign_vlan'))

        try:
            
            commands = [
                f'interface {port}',
                'switchport mode access',
                f'switchport access vlan {vlan_id}',
                'no shutdown'
            ]
            app.logger.info(f"Enviando comandos al switch {switch_name}: {commands}")
            result = filtered_nr.run(
                task=netmiko_send_config,
                config_commands=commands,
                enable=True,  # Esto asegura que use el modo privilegiado
            )
            print_result(result)
            app.logger.debug(f"Salida de comandos: {result}")
            
            # Guardar la configuración
            app.logger.info(f"Guardando configuración en switch {switch_name}")
            save_result = filtered_nr.run(task=netmiko_send_command, command_string="write memory")
            app.logger.debug(f"Salida de guardar configuración: {save_result}")
            
            
            app.logger.info(f"VLAN {vlan_id} asignada al puerto {port} en switch {switch_name}")
            flash(f'VLAN {vlan_id} asignada al puerto {port} en switch {switch_name}.', 'success')

        except Exception as e:
            app.logger.error(f"Error al asignar VLAN en {switch_name}: {e}")
            flash(f'Error al conectar con {switch_name}: {e}', 'danger')
            return redirect(url_for('assign_vlan'))
        return redirect(url_for('vlans'))
    
    return render_template('assign_vlan.html')



@app.route('/backups')
@login_required
def backups():
    backup_dir = app.config['BACKUP_DIR']
    if not os.path.exists(backup_dir):
        os.makedirs(backup_dir)
    backup_files = os.listdir(backup_dir)
    return render_template('backups.html', backup_files=backup_files)

@app.route('/download_backup/<filename>')
@login_required
def download_backup(filename):
    backup_dir = app.config['BACKUP_DIR']
    return send_from_directory(directory=backup_dir, path=filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
