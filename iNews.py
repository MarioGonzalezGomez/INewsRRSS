import ftplib
import getpass
import sys

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
                arg = parts[1] if len(parts) > 1 else None

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

                else:
                    print("Unknown command. Try 'ls', 'cd', 'read', 'pwd', 'exit'")

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

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Pre-filled arguments for faster testing if needed
        # python check_inews.py <ip> <user> <pass>
        host = sys.argv[1]
        user = sys.argv[2]
        password = sys.argv[3]
    else:
        print("--- iNews Connection Shell ---")
        host = input("iNews Server IP: ")
        if not host: 
            # Default from previous context if user hits enter (optional convenience)
            if '172.17.112.32' in input("Use last IP 172.17.112.32? (enter for yes, any key for no): "):
                 pass
            
        if host == "": host = "172.17.112.32"

        user = input(f"Username (default tdigital): ") or "tdigital"
        password = getpass.getpass("Password: ")

    interactive_inews_shell(host, user, password)