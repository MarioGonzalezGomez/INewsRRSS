import ftplib
import getpass
import sys
import json
import argparse

def interactive_inews_shell(host, user, password):
    ftp = None
    try:
        print(f"Connecting to {host}...")
        ftp = ftplib.FTP(host)
        print(f"Logging in as {user}...")
        ftp.login(user, password)
        print("\nLogin successful!")
        print("-------------------------------------------------------")
        print("Interactive iNews Shell")
        print("Commands: 'ls', 'cd <folder>', 'read <file>', 'pwd', 'exit'")
        print("-------------------------------------------------------")

        try:
            ftp.sendcmd('SITE CHARSET UTF-8')
        except:
            pass

        current_path = "/"
        
        while True:
            try:
                # Get clean prompt
                command_line = input(f"iNews:{current_path}> ").strip()
                if not command_line:
                    continue
                
                parts = command_line.split()
                cmd = parts[0].lower()
                arg = " ".join(parts[1:]) if len(parts) > 1 else None

                if cmd in ['exit', 'quit']:
                    break
                
                elif cmd == 'ls':
                    print("Listing files...")
                    try:
                        files = []
                        ftp.retrlines('LIST', files.append)
                        for f in files:
                            print(f)
                        if not files:
                            print("(Empty directory)")
                    except ftplib.error_perm as e:
                        print(f"Permission error: {e}")

                elif cmd == 'cd':
                    if not arg:
                        print("Usage: cd <folder_name>")
                        continue
                    try:
                        if arg == "..":
                            ftp.cwd("..")
                        else:
                            ftp.cwd(arg)
                        current_path = ftp.pwd()
                    except ftplib.error_perm as e:
                        print(f"Error changing directory: {e}")

                elif cmd == 'pwd':
                    print(ftp.pwd())

                elif cmd == 'read':
                    if not arg:
                        print("Usage: read <filename>")
                        continue
                    print(f"Reading {arg}...")
                    def print_line(line):
                        print(line)
                    try:
                        # Try retrieving as ASCII text
                        ftp.retrlines(f'RETR {arg}', print_line)
                    except ftplib.error_perm as e:
                        print(f"Error reading file: {e}")

                elif cmd == 'tree':
                    # Muestra un árbol de carpetas desde el directorio actual
                    max_depth = int(arg) if arg and arg.isdigit() else 2
                    print(f"Mostrando árbol (profundidad máx: {max_depth})...")
                    _print_tree(ftp, ftp.pwd(), "", max_depth, 0)

                else:
                    print("Unknown command. Try 'ls', 'cd', 'read', 'pwd', 'tree [depth]', 'exit'")

            except KeyboardInterrupt:
                print("\nType 'exit' to quit.")
            except Exception as e:
                print(f"Error executing command: {e}")

    except ftplib.all_errors as e:
        print(f"\nConnection Error: {e}")
    finally:
        if ftp:
            try:
                ftp.quit()
            except:
                pass
            print("\nDisconnected.")


def _print_tree(ftp, base_path, prefix, max_depth, current_depth):
    """Imprime un árbol de directorios FTP recursivamente."""
    if current_depth >= max_depth:
        return
    
    try:
        ftp.cwd(base_path)
        lines = []
        ftp.retrlines('LIST', lines.append)
        
        # Filtrar solo directorios
        dirs = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 9 and line.startswith('d'):
                name = " ".join(parts[8:])
                dirs.append(name)
            elif len(parts) < 9 and parts and line.startswith('d'):
                dirs.append(parts[-1])
        
        for i, d in enumerate(dirs):
            is_last = (i == len(dirs) - 1)
            connector = "└── " if is_last else "├── "
            print(f"{prefix}{connector}{d}")
            
            next_prefix = prefix + ("    " if is_last else "│   ")
            child_path = f"{base_path.rstrip('/')}/{d}"
            _print_tree(ftp, child_path, next_prefix, max_depth, current_depth + 1)
            
    except ftplib.error_perm:
        pass
    except Exception as e:
        print(f"{prefix}  (error: {e})")


def load_config_credentials(config_path: str):
    """Lee las credenciales de iNews del archivo de configuración JSON."""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        inews = config.get("inews", {})
        host = inews.get("host")
        user = inews.get("user")
        password = inews.get("password")
        
        if not host or not user or not password:
            print(f"ERROR: Faltan credenciales en {config_path} (host/user/password)")
            sys.exit(1)
        
        return host, user, password
    except FileNotFoundError:
        print(f"ERROR: No se encontró el archivo {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: JSON inválido en {config_path}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='iNews Interactive Shell')
    parser.add_argument('--config', '-c', type=str, default=None,
                        help='Ruta al config.json para leer credenciales automáticamente')
    parser.add_argument('host', nargs='?', default=None, help='iNews Server IP')
    parser.add_argument('user', nargs='?', default=None, help='Username')
    parser.add_argument('password', nargs='?', default=None, help='Password')
    
    args = parser.parse_args()
    
    if args.config:
        # Modo automático: leer credenciales del config.json
        host, user, password = load_config_credentials(args.config)
        print(f"--- iNews Shell (credenciales de {args.config}) ---")
    elif args.host and args.user and args.password:
        # Modo argumentos directos
        host = args.host
        user = args.user
        password = args.password
    else:
        # Modo interactivo
        print("--- iNews Connection Shell ---")
        host = input("iNews Server IP: ")
        if host == "":
            host = "172.17.112.32"
        user = input(f"Username (default tdigital): ") or "tdigital"
        password = getpass.getpass("Password: ")
    
    interactive_inews_shell(host, user, password)