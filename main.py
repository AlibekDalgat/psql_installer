import argparse
import paramiko
import os
import subprocess

def parse_arguments():
    parser = argparse.ArgumentParser(description="Установка и настройка PostgreSQL на удалённом хосте.")
    parser.add_argument("servers", help="Список IP-адресов серверов или имен хостов, разделенных запятыми.")
    return parser.parse_args()

def connect_to_server(server):
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        key_filename = os.environ.get("SSH_KEY_FILENAME")
        if not key_filename:
            raise RuntimeError("Переменная окружения SSH_KEY_FILENAME не установлена.")
        ssh_client.connect(hostname=server, username="root", key_filename=key_filename)
        print(f"Успешное подключение к серверу {server}")
        return ssh_client
    except Exception as e:
        print(f"Ошибка подключения к серверу {server}: {e}")
        return None

def get_server_load(ssh_client):
    try:
        # CPU
        stdin, stdout, stderr = ssh_client.exec_command("top -bn1 | grep 'Cpu(s)' | awk '{print $2+$4}'")
        cpu_usage = float(stdout.read().decode().strip())
        # Memory
        stdin, stdout, stderr = ssh_client.exec_command("free -m | awk 'NR==2{print $3/$2 * 100}'")
        memory_usage = float(stdout.read().decode().strip())

        return cpu_usage, memory_usage
    except Exception as e:
        print(f"Ошибка получения загруженности сервера: {e}")
        return None, None

def choose_target_server(server_loads):
    if not server_loads:
        print("Нет доступных серверов.")
        return None

    least_loaded_server = None
    min_load = float('inf')

    for server, load in server_loads.items():
        total_load = load["cpu"] + load["memory"]
        if total_load < min_load:
            min_load = total_load
            least_loaded_server = server

    if least_loaded_server:
        print(f"Выбранный сервер: {least_loaded_server} (CPU: {server_loads[least_loaded_server]['cpu']}%, Memory: {server_loads[least_loaded_server]['memory']}%)")
        return least_loaded_server
    else:
        print("Не удалось определить наименее загруженный серве.")
        return None


def install_postgresql(ssh_client, server):
    try:
        # Determine the OS type
        stdin, stdout, stderr = ssh_client.exec_command("cat /etc/os-release | grep '^ID=' | cut -d'=' -f2")
        os_id = stdout.read().decode().strip().replace('"','')

        if os_id in ['debian', 'ubuntu']:
            print(f"Установка PostgreSQL на сервер {server} (Debian/Ubuntu)")
            commands = [
                "apt-get update",
                "apt-get install -y postgresql postgresql-contrib"
            ]
        elif os_id in ['centos', 'rhel', 'almalinux']:
            print(f"Установка PostgreSQL на сервер {server} (CentOS/RHEL/AlmaLinux)")
            commands = [
                "yum install -y postgresql-server postgresql-contrib",
                "postgresql-setup initdb"
            ]
        else:
            print(f"Неподдерживающая ОС: {os_id}")
            return False

        for cmd in commands:
            print(f"Выполнение: {cmd}")
            stdin, stdout, stderr = ssh_client.exec_command(cmd)
            for line in stdout:
                print(line.strip())
            for line in stderr:
                print(line.strip())

        if os_id in ['debian', 'ubuntu']:
            stdin, stdout, stderr = ssh_client.exec_command("systemctl enable postgresql && systemctl start postgresql")
        elif os_id in ['centos', 'rhel', 'almalinux']:
             stdin, stdout, stderr = ssh_client.exec_command("systemctl enable postgresql && systemctl start postgresql") #same command, can be refactored

        print(f"PostgreSQL установлен на сервер {server}")
        return True
    except Exception as e:
        print(f"Ошибка установки PostgreSQL на сервер {server}: {e}")
        return False


def configure_postgresql(ssh_client, server, student_server_ip):
    try:
        stdin, stdout, stderr = ssh_client.exec_command("su postgres -c \"psql -d postgres -c 'SHOW config_file' 2>/dev/null | sed -n '3p' | awk '{print $1}'\"")
        pg_conf_path = stdout.read().decode().strip()

        cmd = f"sed -i \"s/#listen_addresses = 'localhost'/listen_addresses = '*' /\" {pg_conf_path}"
        stdin, stdout, stderr = ssh_client.exec_command(cmd)
        print(stdout.read().decode())

        stdin, stdout, stderr = ssh_client.exec_command("su postgres -c \"psql -d postgres -c 'SHOW hba_file' 2>/dev/null | sed -n '3p' | awk '{print $1}'\"")
        pg_hba_path = stdout.read().decode().strip()

        cmd = f"echo 'host all student {student_server_ip}/32 md5' | tee -a {pg_hba_path}"
        stdin, stdout, stderr = ssh_client.exec_command(cmd)
        print(stdout.read().decode())

        stdin, stdout, stderr = ssh_client.exec_command("systemctl reload postgresql")
        print(stdout.read().decode())

        print(f"PostgreSQL настроен на сервере {server}")
        return True
    except Exception as e:
        print(f"Ошибка настройки PostgreSQL на сервер {server}: {e}")
        return False


def verify_postgresql_connection(ssh_client, server):
    try:
        stdin, stdout, stderr = ssh_client.exec_command("su postgres -c \"psql -d postgres -c 'SELECT 1' 2>/dev/null | sed -n '3p' | awk '{print $1}' | tr -d '[:space:]'\"")
        output = stdout.read().decode().strip()

        if "1" in output:
            print(f"Соединение с PostgreSQL успешно проверено на сервере {server}")
            return True
        else:
            print(f"Проверка соединения PostgreSQL не удалась на сервере {server}. Вывод: {output}")
            return False
    except Exception as e:
        print(f"Ошибка проверки соединения PostgreSQL на сервере {server}: {e}")
        return False



if __name__ == "__main__":
    args = parse_arguments()
    servers = args.servers.split(",")
    print(f"Сервера на проверку: {servers}")

    server_loads = {}
    for server in servers:
        ssh_client = connect_to_server(server)
        if ssh_client:
            cpu_usage, memory_usage = get_server_load(ssh_client)
            if cpu_usage is not None and memory_usage is not None:
                server_loads[server] = {"cpu": cpu_usage, "memory": memory_usage}
                print(f"Сервер {server}: использование CPU = {cpu_usage}%, использование Memory = {memory_usage}%")
            ssh_client.close()
        else:
            print(f"Пропуск {server} из-за ошибки подключения.")

    print(f"Загруженность серверов: {server_loads}")

    target_server = choose_target_server(server_loads)
    if target_server:
        print(f"Целевой хост для установки PostgreSQL: {target_server}")
    else:
        print("Не был отобран целевой хост.")

    if target_server:
        ssh_client = connect_to_server(target_server)
        if ssh_client:
            if install_postgresql(ssh_client, target_server):
                student_server_ip = None
                for server in servers:
                    if server != target_server:
                        student_server_ip = server
                        break

                if student_server_ip:
                    print(f"IP второго сервера с пользователем student: {student_server_ip}")
                    if configure_postgresql(ssh_client, target_server, student_server_ip):
                        print("PostgreSQL успешно настроен.")
                    else:
                        print("Не удалось настроить PostgreSQL.")
                else:
                    print("Не получилось определить IP второго сервера с пользователем student.")

                if verify_postgresql_connection(ssh_client, target_server):
                    print("PostgreSQL работает корректно.")
                else:
                    print("PostgreSQL работает некорректно.")

            else:
                print("Установка PostgreSQL провалилась.")
            ssh_client.close()
        else:
            print(f"Не удалось установить соединение с {target_server} для установки.")
    else:
        print("Целевой хост не выбран.")
