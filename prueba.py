from nornir import InitNornir  # Inicializador del plugin
from nornir_utils.plugins.functions import print_result  # Función para imprimir resultados
from nornir_netmiko import netmiko_send_command  # Tarea de Netmiko

# Inicializa Nornir con el archivo de configuración "config.yml"
sw = 'S19-Scarlett'
nr = InitNornir(config_file="config.yml")

# Filtra el inventario para obtener solo el host deseado
filtered_nr = nr.filter(name=sw)

# Ejecuta la tarea en el host filtrado
result = filtered_nr.run(
    task=netmiko_send_command,
    command_string="show vlan brief"
)

# Imprime los resultados
print_result(result)
