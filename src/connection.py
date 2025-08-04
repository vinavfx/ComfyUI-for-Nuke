# -----------------------------------------------------------
# AUTHOR --------> Francisco Contreras
# OFFICE --------> Senior VFX Compositor, Software Developer
# WEBSITE -------> https://vinavfx.com
# -----------------------------------------------------------
import sys
import json
import traceback
from collections import OrderedDict

if sys.version_info.major == 2:
    import urllib2 as urllib2  # type: ignore
else:
    import urllib.request as urllib2

import nuke  # type: ignore
from ..env import IP, PORT


def GET(relative_url):
    url = 'http://{}:{}/{}'.format(IP, PORT, relative_url)
    
    # Добавляем правильные заголовки и таймаут
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache'
    }

    try:
        request = urllib2.Request(url, headers=headers)
        
        # ВАЖНО: Отключаем прокси для localhost
        no_proxy_handler = urllib2.ProxyHandler({})
        opener = urllib2.build_opener(no_proxy_handler)
        
        # Увеличиваем таймаут
        response = opener.open(request, timeout=30)
        data = response.read().decode()
        
        # Проверяем, что получили валидный JSON
        if not data.strip():
            raise Exception("Empty response from server")
            
        return json.loads(data, object_pairs_hook=OrderedDict)
        
    except Exception as e:
        # Более детальная информация об ошибке
        error_msg = 'Error connecting to server {} on port {} !\nDetails: {}'.format(IP, PORT, str(e))
        print(error_msg)  # Выводим в консоль для отладки
        nuke.message(error_msg)
        return None


def check_connection():
    url = 'http://{}:{}'.format(IP, PORT)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': '*/*',
        'Connection': 'keep-alive'
    }
    
    try:
        request = urllib2.Request(url, headers=headers)
        
        # ВАЖНО: Отключаем прокси для localhost
        no_proxy_handler = urllib2.ProxyHandler({})
        opener = urllib2.build_opener(no_proxy_handler)
        
        response = opener.open(request, timeout=10)
        
        if response.getcode() == 200:
            print("Connection successful to {}:{}".format(IP, PORT))
            return True
        else:
            print("Server responded with code: {}".format(response.getcode()))
            return False
            
    except Exception as e:
        error_msg = 'Error connecting to server {} on port {} !\nDetails: {}'.format(IP, PORT, str(e))
        print(error_msg)
        nuke.message(error_msg)
        return False


def POST(relative_url, data={}):
    url = 'http://{}:{}/{}'.format(IP, PORT, relative_url)
    
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Connection': 'keep-alive'
    }
    
    bytes_data = json.dumps(data).encode('utf-8')
    request = urllib2.Request(url, bytes_data, headers)

    try:
        # ВАЖНО: Отключаем прокси для localhost
        no_proxy_handler = urllib2.ProxyHandler({})
        opener = urllib2.build_opener(no_proxy_handler)
        
        response = opener.open(request, timeout=30)
        return ''

    except urllib2.HTTPError as e:
        try:
            error_bytes = e.read()
            error_str = error_bytes.decode('utf-8', errors='ignore').strip()

            try:
                error = json.loads(error_str)
            except json.JSONDecodeError:
                nuke.message('Error parsing JSON from server')
                return 'ERROR: JSON parsing'

            errors = 'ERROR: {}\n\n'.format(error['error']['message'].upper())
            node_errors = error['node_errors'] if error['node_errors'] else {}

            for name, value in node_errors.items():
                nuke.toNode(name).setSelected(True)
                errors += '{}:\n'.format(name)

                for err in value['errors']:
                    errors += ' - {}: {}\n'.format(
                        err['details'], err['message'])

                errors += '\n'

            return errors
        except:
            nuke.message(traceback.format_exc())

    except Exception as e:
        error_msg = 'Error in POST request: {}'.format(str(e))
        print(error_msg)
        return error_msg


def convert_to_utf8(data):
    if isinstance(data, dict):
        return {convert_to_utf8(key): convert_to_utf8(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [convert_to_utf8(element) for element in data]
    elif isinstance(data, str):
        return data.encode('utf-8') if sys.version_info[0] < 3 else data
    elif sys.version_info[0] < 3 and isinstance(data, unicode):
        return data.encode('utf-8')
    else:
        return data


def interrupt():
    error = POST('interrupt')

    if error:
        nuke.message(error)
