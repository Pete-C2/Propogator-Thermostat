"""Propagator Thermostat
Reads the configuration from an associated xml file.
Presents a set of webpages to display the temperature.
Controls the temperature of the propagator using a sensor (typically inserted into the soil).
"""

from flask import Flask, render_template, request
import datetime
import xml.etree.ElementTree as ET
import os
import threading
import time
import csv
import RPi.GPIO as GPIO
from max31855 import MAX31855, MAX31855Error

app = Flask(__name__)

# Initialisation

# Read config from xml file

# Find directory of the program
dir = os.path.dirname(os.path.abspath(__file__))
# Get the configuration
tree = ET.parse(dir+'/config.xml')
root = tree.getroot()
HW = root.find('HARDWARE')
sensors = root.find('SENSORS')
display = root.find('DISPLAY')
logging = root.find('LOGGING')

# Read hardware configuration
# Clock
CLK = HW.find('CLOCK')
clock_pin = int(CLK.find('PIN').text)
# Data
DATA = HW.find('DATA')
data_pin = int(DATA.find('PIN').text)
# Chip Selects
cs_pins = []
relay_pins = []
for child in sensors:
     cs_pins.append(int(child.find('CSPIN').text))
     relay_pins.append(int(child.find('RELAY').text))

# Read display settings configuration
units = display.find('UNITS').text.lower()
title = display.find('TITLE').text

channel_names = []
for child in sensors:
     channel_names.append(child.find('NAME').text)
     
# Create a dictionary called temps to store the temperatures and names:
temps = {}
channel = 1
for child in sensors:
     temps[channel] = {'name' : child.find('NAME').text, 'temp' : ''}
     channel = channel + 1

# Read logging
logging = root.find('LOGGING')
log_interval = int(logging.find('INTERVAL').text)*60  # Interval in minutes from config file
log_status = "Off"  # Values: Off -> On -> Stop -> Off

# Control
control_interval = 10 # seconds. Interval between control measurements
set_temperature = 20 

HeaterThread().start()

# Flask web page code

@app.route('/')
def index():
     global title
     global log_status
     global pending_note
     now = datetime.datetime.now()
     timeString = now.strftime("%H:%M on %d-%m-%Y")
     if log_status == "On":
          logging = "Active"
     else:
          logging = "Inactive"
     templateData = {
                     'title' : title,
                     'time': timeString,
                     'logging' : logging,
                    }
     return render_template('main.html', **templateData)

@app.route("/", methods=['POST'])   # Seems to be run regardless of which page the post comes from
def log_button():
     global log_status
     global pending_note
     if request.method == 'POST':
          # Get the value from the submitted form  
          submitted_value = request.form['logging']
          if submitted_value == "Log_Start":
               if (log_status == "Off"):
                    log_status = "On"
                    LogThread().start()
                    
          if submitted_value =="Log_Stop":   
               if (log_status == "On"):
                    log_status = "Stop"
     return index()
 
@app.route('/temp')
def temp():
     now = datetime.datetime.now()
     timeString = now.strftime("%H:%M on %d-%m-%Y")

     thermocouples = []

     channel = 1
     for cs_pin in cs_pins:
          thermocouples.append(MAX31855(cs_pin, clock_pin, data_pin, units, GPIO.BOARD))

     for thermocouple in thermocouples:
          if (channel == 1):
               air_temp = int(thermocouple.get_rj())
          try:
                tc = str(int(thermocouple.get()))+u'\N{DEGREE SIGN}'+units.upper()
          except MAX31855Error as e:
                tc = "Error: "+ e.value

          temps[channel]['temp'] = tc
          channel = channel + 1

     for thermocouple in thermocouples:
          thermocouple.cleanup()
       
     templateData = {
                'title' : title,
                'time': timeString,
                'air' : air_temp,
                'temps' : temps,
                'units' : units.upper()
                }

     return render_template('temperature.html', **templateData)

@app.route('/confirm')
def confirm():
     templateData = {
                'title' : title
                }
     return render_template('confirm.html', **templateData)

@app.route('/shutdown')
def shutdown():
     command = "/usr/bin/sudo /sbin/shutdown +1"
     import subprocess
     process = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
     output = process.communicate()[0]
     print output
     templateData = {
                'title' : title
                }
     return render_template('shutdown.html', **templateData)

@app.route('/cancel')
def cancel():
     command = "/usr/bin/sudo /sbin/shutdown -c"
     import subprocess
     process = subprocess.Popen(command.split(), stdout=subprocess.PIPE)
     output = process.communicate()[0]
     print output

     return index()

# Logging code: write a CSV file with header and then one set of sensor measurements per interval

class LogThread ( threading.Thread ):

     def run ( self ):
          global log_status
          global dir
          global log_interval
          global cs_pins
          global clock_pin
          global data_pin
          global units
          
          now = datetime.datetime.now()
          filetime = now.strftime("%Y-%m-%d-%H-%M")
          filename=dir+'/logging/'+filetime+'_temperature_log.csv'
          with open(filename, 'ab') as csvfile:
               logfile = csv.writer(csvfile, delimiter=',', quotechar='"')
               row = ["Date-Time"]
               for channels in temps:
                    row.append( temps[channels]['name'])
               logfile.writerow(row)

          while log_status == "On":
               with open(filename, 'ab') as csvfile:
                    logfile = csv.writer(csvfile, delimiter=',', quotechar='"')
                    now = datetime.datetime.now()
                    row = [now.strftime("%d/%m/%Y %H:%M")]
                    thermocouples = []
                    for cs_pin in cs_pins:
                         thermocouples.append(MAX31855(cs_pin, clock_pin, data_pin, units, GPIO.BOARD))

                    for thermocouple in thermocouples:
                         try:
                               tc = int(thermocouple.get())
                         except MAX31855Error as e:
                               tc = ""
                         row.append(tc)
 
                    for thermocouple in thermocouples:
                         thermocouple.cleanup()
                    logfile.writerow(row)
               time.sleep(log_interval)
          log_status = "Off"

# Heater control code: if the temperature is too cold then turn the heater on (typically using a relay), else turn it off.

class HeaterThread ( threading.Thread ):

     def run ( self ):
          global control_interval
          global cs_pins
          global clock_pin
          global data_pin
          global units

          GPIO.setmode(GPIO.BOARD)

          for relay_pin in relay_pins:
               GPIO.setup(relay_pin, GPIO.OUT)
               GPIO.output(relay_pin, GPIO.LOW)
          
          while 1: # Control the heater forever while powered
               thermocouples = []
               for cs_pin in cs_pins:
                    thermocouples.append(MAX31855(cs_pin, clock_pin, data_pin, units, GPIO.BOARD))

               for thermocouple, relay_pin in zip(thermocouples, relay_pins):
                    try:
                         tc = int(thermocouple.get())
                         if tc < set_temperature:
                              GPIO.output(relay_pin, GPIO.HIGH) # Turn on relay
                         else
                              GPIO.output(relay_pin, GPIO.LOW) # Turn off relay
                    except MAX31855Error as e:
                         tc = ""
                         GPIO.output(relay_pin, GPIO.LOW) # Turn off Relay (fault condition - avoid overheating)
  
               for thermocouple in thermocouples:
                    thermocouple.cleanup()
               time.sleep(control_interval)

if __name__ == '__main__':
     app.run(debug=True, host='0.0.0.0')
     
     