#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Example (these rules are set by the python web server below)
#iptables -t nat -A PREROUTING -s allowed.visitor.ip -d your.outside.ip -p tcp --dport 443 -j DNAT --to-destination ssl-vpn-device-ip:443
#iptables -A FORWARD -s allowed.visitor.ip/32 -d ssl-vpn-device-ip/32 -o eth0 -p tcp -m tcp --dport 443 -j ACCEPT

# You might also need to set this additional route :
# (Example) iptables -t nat -A POSTROUTING -s 192.168.1.0/24 -d 192.168.1.2/32 -p tcp -m tcp --dport 443 -j SNAT --to-source 192.168.1.1
# Where 192.168.1.0 is your internal network, 192.168.1.2 is your SSL-VPN device (external port) and 192.168.1.1 is your firewall/router

import http.server
from urllib.parse import urlparse, parse_qs
import logging
import socketserver
import ssl
import subprocess
import html
import os
import sys
import signal

PASSWORD = "yoursuperduperpassword"

logging.basicConfig(
    filename='/var/log/ivantiunlocker.log',  # Log
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',  # Log-Format
)

class MyLogger:
    def write(self, message):
        # Skip empty messages or empty lines
        if message != '\n':
            logging.info(message.strip())
    def flush(self):
        pass

sys.stdout = MyLogger()
sys.stderr = MyLogger()

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True  # End threads after server closed
    allow_reuse_address = True

    def serve_forever(self, poll_interval=0.5):
        self.socket.settimeout(1)
        while True:
            try:
                self.handle_request()
            except socket.timeout:
                pass  # Currently no connection
            except Exception as e:
                logging.error("Error in server loop: %s", str(e))

class Handler(http.server.BaseHTTPRequestHandler):
    def version_string(self):
        return "IvantiUnlocker/1.0" # Enter own name so no one finds you !

    def do_GET(self):
        logging.info("%s %s", self.command, self.path)

        # Protection against long headers (eg. X-Forwarded-For)
        for header, value in self.headers.items():
            if len(value) > 1024:  # Can be adjusted
                self.send_error(400, "Header too long")
                logging.warning("Too long HTTP-header from %s: %s=%d characters", self.client_address[0], header, len(value))
                return
                
        if not self.path.startswith("/") or ".." in self.path:
            self.send_error(400, "Invalid path")
            return

        query = parse_qs(urlparse(self.path).query)
        passwort = query.get("passwort", [""])[0]

        if len(passwort) > 50: # Prevent DOS attacks
            self.send_error(400, "Password too long")
            return

        client_ip = self.client_address[0]

        if self.path.startswith("/checkaccess") and passwort == PASSWORD:
            self.allow_ip(self.client_address[0])

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(("""
            <html>
              <body>
                  <p>IP <b>{}</b> was enabled.</p>
                  <p>You now can open <a href="https://yourapplianceaddresshere">Ivanti Secure Connect</a>.</p>
              </body>
            </html>
            """.format(html.escape(client_ip))).encode("utf-8"))
        else:
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(("""
            <html>
              <head>
                <style>
                  html, body {
                    height: 100%;
                    margin: 0;
                  }
                  body {
                    display: flex;
                    justify-content: center;
                    align-items: center;
                    font-family: Arial, sans-serif;
                    text-align: center;
                  }
                  form {
                    padding: 20px;
                    border: 1px solid #ccc;
                    border-radius: 8px;
                    box-shadow: 0px 4px 8px rgba(0, 0, 0, 0.1);
                  }
                  input[type="text"] {
                    padding: 8px;
                    font-size: 16px;
                    width: 200px;
                    margin-bottom: 10px;
                  }
                  input[type="submit"] {
                    padding: 8px 16px;
                    font-size: 16px;
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                  }
                  input[type="submit"]:hover {
                    background-color: #45a049;
                  }
                </style>
              </head>
              <body>
                <form action="/checkaccess" method="get">
                  Password: <input type="password" name="passwort" autofocus>
                  <input type="submit" value="Send">
                </form>
              </body>
            </html>
            """).encode("utf-8"))

    def allow_ip(self, ip, target_ip='ssl-vpn-device-ip', target_port=443):
        try:
            # Check existing FORWARD rules
            result = subprocess.check_output(['iptables', '-S'])
            rules = result.decode('utf-8').splitlines()
            # Prepare rule
            forward_rule = '-A FORWARD -s {}/32 -d ssl-vpn-device-ip/32 -o eth0 -p tcp -m tcp --dport 443 -j ACCEPT'.format(ip)
            append_rule_to_file(forward_rule)
            # Check if rule exists already
            for line in rules:
                if line.strip() == forward_rule:
                    logging.info("FORWARD rule for {} exists already".format(str(ip)))
                    return
            # Regel setzen
            subprocess.check_call([
                'iptables', '-A', 'FORWARD',
                '-s', ip,
                '-d', target_ip,
                '-o', 'eth0',
                '-p', 'tcp', '--dport', '443',
                '-j', 'ACCEPT'
            ])
            logging.info("FORWARD rule for {} has been set".format(str(ip)))
        except subprocess.CalledProcessError as e:
            logging.error("Error while setting FORWARD rule for {}: {}".format(str(ip), e))
        except Exception as e:
            logging.error("Unexpected error with FORWARD for {}: {}".format(str(ip), e))
        try:
            # Check existing PREROUTING rules
            result = subprocess.check_output(['iptables','-t','nat','-S'])
            rules = result.decode('utf-8').splitlines()
            # Prepare rule
            prerouting_rule = '-t nat -A PREROUTING -s {}/32 -d your.outside.ip/32 -p tcp --dport 443 -j DNAT --to-destination {}:{}'.format(ip, target_ip, target_port)
            append_rule_to_file(prerouting_rule)
            # Check if rule exists already
            for line in rules:
                if line.strip() == prerouting_rule:
                    logging.info("PREROUTING-rule for {} exists already".format(str(ip)))
                    return
            # Regel setzen
            subprocess.check_call([
                'iptables','-t','nat','-A','PREROUTING',
                '-s', ip,
                '-d', 'your.outside.ip',
                '-p', 'tcp', '--dport', '443',
                '-j', 'DNAT', '--to-destination', '{}:{}'.format(target_ip, target_port)
            ])
            logging.info("PREROUTING-rule for {} has been set".format(str(ip)))
        except subprocess.CalledProcessError as e:
            logging.error("Error while setting PREROUTING-rule for {}: {}".format(str(ip), e))
        except Exception as e:
            logging.error("Unexpected error with PREROUTING for {}: {}".format(str(ip), e))
            
def append_rule_to_file(rule, filename='/afiletostorerulesinaddition'):
    try:
        if not os.path.exists(os.path.dirname(filename)):
            os.makedirs(os.path.dirname(filename))
        if os.path.isfile(filename):
            with open(filename, 'r') as f:
                lines = f.read().splitlines()
            if rule in lines:
                return
        with open(filename, 'a') as f:
            f.write(rule + '\n')
    except Exception as e:
        logging.error("Error while writing the rule to file: {}".format(e))

def run():
    while True:
        try:
            httpd = ThreadedHTTPServer(('my.listening.ip.here', 443), Handler)
            httpd.timeout = 15
            ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLSv1_2)
            ssl_context.load_cert_chain(certfile="/server.crt", keyfile="/server.key")
            ssl_context.set_ciphers("ECDHE+AESGCM:!ECDSA")
            httpd.socket = ssl_context.wrap_socket(httpd.socket, server_side=True)
            httpd.socket.settimeout(15)
            logging.info("Unlock-Webserver running on port 443 (HTTPS)...")
            httpd.serve_forever()
        except ssl.SSLError as e:
            logging.error("SSL-error: %s", str(e))
        except OSError as e:
            logging.error("Socket-error: %s", str(e))
        except Exception as e:
            logging.error("Unexpected error: %s\n%s", str(e), traceback.format_exc())
        logging.info("Neustart in 5 seconds...")
        time.sleep(3)
        
if __name__ == '__main__':
    run()
