import re
from datetime import datetime, time

def roc_to_common_date(roc_date):
    roc_date_format = re.compile(r'(\d{3})(\d{2})(\d{2})')
    m = roc_date_format.match(roc_date)
    if m:
        year = int(m.group(1)) + 1911
        return '{}-{}-{}'.format(year, m.group(2), m.group(3))
    else:
        return roc_date

def parse_power_date_time(raw_str):
    tokens = re.split('\s|~', raw_str)
    if len(tokens) != 3:
        return (None, None, None)

    event_date = tokens[0].replace('/', '-')
    start_time = tokens[1] + ':00'
    end_time = tokens[2] + ':00'
    return (event_date, start_time, end_time)

def parse_water_road_time(raw_str):
    if raw_str:
        match = parse_water_road_time.pattern.search(raw_str)
    else:
        match = None

    if match:
        start = _process_time(match.group(1), match.group(2), match.group(3))
        end = _process_time(match.group(4), match.group(5), match.group(6))
        return (start, end)
    else:
        return (None, None)

# static object
parse_water_road_time.pattern = re.compile('(上午|下午)?(\d+時?)(\d+分)?至.*?(上午|下午)?(\d+時)(\d+分)?')

def _process_time(prefix, hour, minute):
    h = int(hour.replace('時', ''))
    if minute:
        m = int(minute.replace('分', ''))
    else:
        m = 0

    if prefix == '下午':
        h = h + 12

    return time(hour=h, minute=m, second=0).strftime('%H:%M:%S')