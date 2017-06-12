# coding=utf-8

from abc import ABCMeta, abstractmethod
from collections import namedtuple
import urllib.parse
import shutil
import time
import uuid
import zipfile
import requests

import os
import psycopg2

import map_converter
import datetime_parser
import location_parser


ldb_name = os.environ['LDB_DATABASE']
ldb_user = os.environ['LDB_USER']
ldb_pass = os.environ['LDB_PASS']
ldb_host = os.environ['LDB_HOST']
ldb_port = os.environ['LDB_PORT']

_DATABASE = ldb_name

Event = namedtuple('Event', ['event_id', 'event_type', 'gov_serial_number',
    'city', 'district', 'road', 'lane_alley_number', 'start_date', 'end_date',
    'start_time', 'end_time', 'description', 'update_status', 'update_time'])


class DataImporter(object):
    __metaclass__ = ABCMeta

    def __init__(self):
        self.connect = psycopg2.connect(dbname=ldb_name, user=ldb_user, password=ldb_pass, host=ldb_host, port=ldb_port)
        self.events = []
        self.groups = []
        self.coordinates = []

    @abstractmethod
    def get_event_type(self):
        pass

    @abstractmethod
    def get_raw_data(self):
        pass

    @abstractmethod
    def generate_events(self, source):
        pass

    def import_data(self):
        source = self.get_raw_data()
        if not source:
            return

        self._mask_old_entries()
        self.generate_events(source)
        self._insert_entries()
        self.connect.commit()        
        self.connect.close()

    def _mask_old_entries(self):
        cursor = self.connect.cursor()
        cursor.execute("""UPDATE event SET update_status = 'old'
            WHERE event_type = %s AND update_status = 'new'""",
            (self.get_event_type(), ))        
        cursor.close()

    def _insert_entries(self):
        cursor = self.connect.cursor()
        cursor.executemany("""INSERT INTO event
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", self.events)
        cursor.executemany("""INSERT INTO event_coord_group(
            group_id,
            event_id)
            VALUES (%s,%s)""", self.groups)
        cursor.executemany("""INSERT INTO event_coordinate(
            coordinate_id,
            latitude,
            longitude,
            group_id)
            VALUES (%s,%s,%s,%s)""", self.coordinates)        
        cursor.close()

class WaterImporter(DataImporter):

    _WATER_SOURCE = 'http://data.taipei/opendata/datalist/apiAccess?scope=resourceAquire&rid=a242ee9b-b954-4ae9-9827-2344c5dfeaea'

    def __init__(self):
        super().__init__()

    def get_event_type(self):
        return 'water'

    def get_raw_data(self):
        response = requests.get(self._WATER_SOURCE)
        if response.status_code == 200:
            print('Web (WATER OUTAGE) request is ok.')
            return response.json()
        else:
            print('Web (WATER OUTAGE) request is NOT ok. Response status code = %s.'
                %(response.status_code))
            return None

    def generate_events(self, source):
        for event_water in source['result']['results']:

            timeinfo = datetime_parser.parse_water_road_time(event_water['Description'])
            
            description_info = location_parser.parse_water_address(event_water['Description'], 'description')

            for coordinate_group in event_water['StopWaterSection_wgs84']['coordinates']:
                
                latitude = coordinate_group[0][1]
                longitude = coordinate_group[0][0]
                
                # Convert coordinate to address
                address = map_converter.convert_coordinate_to_address(latitude, longitude)
                
                location_info = location_parser.parse_water_address(address, 'location')
                
                event_model = Event(
                    event_id=get_uuid(),
                    event_type=self.get_event_type(),
                    gov_serial_number=event_water['SW_No'],
                    city=location_info[0],
                    district=location_info[1],
                    road=location_info[2],
                    lane_alley_number=location_info[3],
                    start_date=datetime_parser.roc_to_common_date(event_water['FS_Date']),
                    end_date=datetime_parser.roc_to_common_date(event_water['FC_Date']),
                    start_time=timeinfo[0],
                    end_time=timeinfo[1],
                    description=description_info[0],
                    update_status='new',
                    update_time=get_current_time()
                )
                self.events.append(event_model)
            
                group_model = (get_uuid(), event_model[0])
                self.groups.append(group_model)
                for coordinate in coordinate_group:
                    coordinate_model = (get_uuid(), coordinate[1],
                        coordinate[0], group_model[0])
                    self.coordinates.append(coordinate_model)


class RoadImporter(DataImporter):

    _ROAD_SOURCE = 'http://data.taipei/opendata/datalist/apiAccess?scope=resourceAquire&rid=201d8ae8-dffc-4d17-ae1f-e58d8a95b162'

    def __init__(self):
        super().__init__()

    def get_event_type(self):
        return 'road'

    def get_raw_data(self):
        response = requests.get(self._ROAD_SOURCE)
        if response.status_code == 200:
            print('Web (ROAD CONSTRUCTION) request is ok.')
            return response.json()
        else:
            print('Web (ROAD CONSTRUCTION) request is NOT ok. Response status code = %s.'
                %(response.status_code))
            return None

    def generate_events(self, source):
        for event in source['result']['results']:
            timeinfo = datetime_parser.parse_water_road_time(event['CO_TI'])

            # Convert TWD97 to WGS84
            latitude, longitude = map_converter.twd97_to_wgs84(float(event['X']), float(event['Y']))
            
            # Convert coordinate to address
            address = map_converter.convert_coordinate_to_address(latitude, longitude)
            
            location_info = location_parser.parse_road_address(address)
            
            event_model = Event(
                event_id=get_uuid(),
                event_type=self.get_event_type(),
                gov_serial_number='#'.join((event['AC_NO'], event['SNO'])),
                city=location_info[0],
                district=location_info[1],
                road=location_info[2],
                lane_alley_number=location_info[3],
                start_date=datetime_parser.roc_to_common_date(event['CB_DA']),
                end_date=datetime_parser.roc_to_common_date(event['CE_DA']),
                start_time=timeinfo[0],
                end_time=timeinfo[1],
                description=event['NPURP'],
                update_status='new',
                update_time=get_current_time()
            )
            self.events.append(event_model)

            group_model = (get_uuid(), event_model[0])
            self.groups.append(group_model)

            coordinate_model = (get_uuid(), latitude, longitude,
                group_model[0])
            self.coordinates.append(coordinate_model)


class PowerImporter(DataImporter):

    _ZIP_FILE = '台灣電力公司_計畫性工作停電資料.zip'
    _POWER_SOURCE = ('http://data.taipower.com.tw/opendata/apply/file/d077004/'
        + urllib.parse.quote(_ZIP_FILE))
    _TEXT_FILE = 'wkotgnews/102.txt'

    def __init__(self):
        super().__init__()

    def get_event_type(self):
        return 'power'

    def get_raw_data(self):
        # Download file
        response = requests.get(self._POWER_SOURCE, stream=True)
        if response.status_code == 200:
            with open(self._ZIP_FILE, 'wb') as fout:
                shutil.copyfileobj(response.raw, fout)
        else:
            print('Download (POWER OUTAGE) file is NOT ok.')
            return

        # Unzip downloaded file
        with zipfile.ZipFile(self._ZIP_FILE) as zip_power:
            file_power = zip_power.extract(self._TEXT_FILE)
            print('Unzipped (POWER OUTAGE) file is "%s".' %file_power)

        # Read the content of txt file
        with open(self._TEXT_FILE, 'r') as fin:
            lines = fin.readlines()

        return [line.strip().split('#') for line in lines[1:]]

    def generate_events(self, source):
        # arrange data and insert to table
        for event in source:
            # Convert address to coordinate
            coordinate = map_converter.convert_address_to_coordinate(event[5])

            location_info = location_parser.parse_power_address(event[5])
            
            # First working period
            timeinfo = datetime_parser.parse_power_date_time(event[3])
            self._get_single_event(event, location_info, timeinfo, coordinate)
            
            # Second working period
            if event[4] and event[4] != '無':
                timeinfo = datetime_parser.parse_power_date_time(event[4])
                self._get_single_event(event, location_info, timeinfo, coordinate)

    def _get_single_event(self, line, location_info, timeinfo, coordinate):
        event_model = Event(
            event_id=get_uuid(),
            event_type=self.get_event_type(),
            gov_serial_number=line[1],
            city='台'+str(location_info[0]),
            district=location_info[1],
            road=location_info[2],
            lane_alley_number=location_info[3],
            start_date=timeinfo[0],
            end_date=timeinfo[0],
            start_time=timeinfo[1],
            end_time=timeinfo[2],
            description=line[2],
            update_status='new',
            update_time=get_current_time()
        )
        self.events.append(event_model)

        group_model = (get_uuid(), event_model[0])
        self.groups.append(group_model)

        coordinate_model = (get_uuid(), float(coordinate[0]),
            float(coordinate[1]), group_model[0])
        self.coordinates.append(coordinate_model)


### Import all types of livelihood data ###
def import_all():
    WaterImporter().import_data()
    RoadImporter().import_data()
    PowerImporter().import_data()

### Create livelihood database ###
def create_database():

    # Connect database
    connect = psycopg2.connect(dbname=ldb_name, user=ldb_user, password=ldb_pass, host=ldb_host, port=ldb_port)
    conn = connect.cursor()

    # Create event table
    conn.execute("""CREATE TABLE event(
        event_id TEXT NOT NULL PRIMARY KEY,
        event_type TEXT NOT NULL,
        gov_serial_number TEXT NOT NULL,
        city TEXT,
        district TEXT,
        road_street_boulevard_section TEXT,
        lane_alley_number TEXT ,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        start_time TEXT,
        end_time TEXT,
        description TEXT,
        update_status TEXT NOT NULL,
        update_time TEXT NOT NULL)""")

    # Create group table
    conn.execute("""CREATE TABLE event_coord_group(
        group_id TEXT NOT NULL PRIMARY KEY,
        event_id TEXT NOT NULL,

        FOREIGN KEY(event_id)
            REFERENCES event(event_id))""")

    # Create coordinate table
    conn.execute("""CREATE TABLE event_coordinate(
        coordinate_id TEXT NOT NULL PRIMARY KEY,
        latitude REAL NOT NULL,
        longitude REAL NOT NULL,
        group_id TEXT NOT NULL,

        FOREIGN KEY(group_id)
            REFERENCES event_coord_group(group_id))""")

    # Save (commit) the changes and close the connection
    connect.commit()
    conn.close()
    connect.close()


def get_current_time():
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())


def get_uuid():
    return str(uuid.uuid4())
