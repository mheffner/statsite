#!/usr/bin/env python

# This is the MIT License
# http://www.opensource.org/licenses/mit-license.php
#
# Copyright (c) 2007,2008 Nick Galbreath
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#

#
# Version 1.0 - 21-Apr-2007
#   initial
# Version 2.0 - 16-Nov-2008
#   made class Gmetric thread safe
#   made gmetrix xdr writers _and readers_
#   Now this only works for gmond 2.X packets, not tested with 3.X
#
# Version 3.0 - 09-Jan-2011 Author: Vladimir Vuksan
#   Made it work with the Ganglia 3.1 data format
#
# Version 3.1 - 30-Apr-2011 Author: Adam Tygart
#   Added Spoofing support
#
# Version 3.2 - 11-Apr-2014 Author: Eugene Alekseev
# Adapted to use as statsite 'sink' to ganglia.


import sys
import argparse
from xdrlib import Packer, Unpacker
import socket

slope_str2int = {'zero':0,
                 'positive':1,
                 'negative':2,
                 'both':3,
                 'unspecified':4}

# could be autogenerated from previous but whatever
slope_int2str = {0: 'zero',
                 1: 'positive',
                 2: 'negative',
                 3: 'both',
                 4: 'unspecified'}

class TransportError(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg

class Gmetric:
    """
    Class to send gmetric/gmond 2.X packets

    Thread safe
    """

    type = ('', 'string', 'uint16', 'int16', 'uint32', 'int32', 'float',
            'double', 'timestamp')
    protocol = ('udp', 'multicast')

    def __init__(self, host, port, protocol):
        if protocol not in self.protocol:
            raise ValueError("Protocol must be one of: " + str(self.protocol))

        for res in socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_DGRAM):
            af, socktype, proto, canonname, sa = res
            try:
                self.socket = socket.socket(af, socktype, proto)
                self.hostport = (sa[0], sa[1])
            except socket.error, e:
                self.socket = None
                continue
            break
        if self.socket is None:
            raise TransportError("Could not open socket.")

        if protocol == 'multicast':
            self.socket.setsockopt(socket.IPPROTO_IP,
                                   socket.IP_MULTICAST_TTL, 20)

    def send(self, NAME, VAL, TYPE='string', UNITS='', SLOPE='both',
             TMAX=60, DMAX=0, GROUP="", SPOOF=""):
        if SLOPE not in slope_str2int:
            raise ValueError("Slope must be one of: " + str(self.slope.keys()))
        if TYPE not in self.type:
            raise ValueError("Type must be one of: " + str(self.type))
        if len(NAME) == 0:
            raise ValueError("Name must be non-empty")

        ( meta_msg, data_msg )  = gmetric_write(NAME, VAL, TYPE, UNITS, SLOPE, TMAX, DMAX, GROUP, SPOOF)
        # print msg

        self.socket.sendto(meta_msg, self.hostport)
        self.socket.sendto(data_msg, self.hostport)

def gmetric_write(NAME, VAL, TYPE, UNITS, SLOPE, TMAX, DMAX, GROUP, SPOOF):
    """
    Arguments are in all upper-case to match XML
    """
    packer = Packer()
    HOSTNAME="test"
    if SPOOF == "":
        SPOOFENABLED=0
    else :
        SPOOFENABLED=1
    # Meta data about a metric
    packer.pack_int(128)
    if SPOOFENABLED == 1:
        packer.pack_string(SPOOF)
    else:
        packer.pack_string(HOSTNAME)
    packer.pack_string(NAME)
    packer.pack_int(SPOOFENABLED)
    packer.pack_string(TYPE)
    packer.pack_string(NAME)
    packer.pack_string(UNITS)
    packer.pack_int(slope_str2int[SLOPE]) # map slope string to int
    packer.pack_uint(int(TMAX))
    packer.pack_uint(int(DMAX))
    # Magic number. Indicates number of entries to follow. Put in 1 for GROUP
    if GROUP == "":
        packer.pack_int(0)
    else:
        packer.pack_int(1)
        packer.pack_string("GROUP")
        packer.pack_string(GROUP)

    # Actual data sent in a separate packet
    data = Packer()
    data.pack_int(128+5)
    if SPOOFENABLED == 1:
        data.pack_string(SPOOF)
    else:
        data.pack_string(HOSTNAME)
    data.pack_string(NAME)
    data.pack_int(SPOOFENABLED)
    data.pack_string("%s")
    data.pack_string(str(VAL))

    return ( packer.get_buffer() ,  data.get_buffer() )

def gmetric_read(msg):
    unpacker = Unpacker(msg)
    values = dict()
    unpacker.unpack_int()
    values['TYPE'] = unpacker.unpack_string()
    values['NAME'] = unpacker.unpack_string()
    values['VAL'] = unpacker.unpack_string()
    values['UNITS'] = unpacker.unpack_string()
    values['SLOPE'] = slope_int2str[unpacker.unpack_int()]
    values['TMAX'] = unpacker.unpack_uint()
    values['DMAX'] = unpacker.unpack_uint()
    unpacker.done()
    return values

def classify_type(value):
    if not value:
        return None
    try:
        ivalue = int(value)
    except ValueError:
        return 'string'
    if ivalue < 0:
        if ivalue < -2147483648:
            return None
        elif ivalue < -32768:
            return 'int32'
        else:
            return 'int16'
    else:
        if ivalue < 65536:
            return 'uint16'
        elif ivalue < 4294967296:
            return 'uint32'
    return None


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument('--protocol', metavar='protocol', nargs='?', default='udp', help="The gmetric internet protocol, either udp or multicast, default udp.")
    parser.add_argument('--host', metavar='host', nargs='?', default='127.0.0.1', help="GMond aggregator hostname to send data to.")
    parser.add_argument('--port', metavar='port', nargs='?', default='8649', help="GMond aggregator port to send data to.")
    parser.add_argument('--name', metavar='name', nargs=1, help="The name of the metric. Can be ommited and read from stdin.")
    parser.add_argument('--value', metavar='value', nargs=1, help="The value of the metric. Can be ommited and read from stdin.")
    parser.add_argument('--units', metavar='units', nargs='?', default='', help="The units for the value, e.g. 'kb/sec'")
    parser.add_argument('--slope', metavar='slope', nargs='?', default='both', help="The sign of the derivative of the value over time, one of zero, positive, negative, both, default=both.")
    parser.add_argument('--type', metavar='type', nargs='?', help="The value data type, one of string, int8, uint8, int16, uint16, int32, uint32, float, double")
    parser.add_argument('--tmax', metavar='tmax', nargs='?', default='60', help="The maximum time in seconds between gmetric calls, default 60.")
    parser.add_argument('--dmin', metavar='dmin', nargs='?', default='0', help="The lifetime in seconds of this metric, default=0, meaning unlimited.")
    parser.add_argument('--group', metavar='group', nargs='?', default='', help="Group metric belongs to. If not specified Ganglia will show it as no_group.")
    parser.add_argument('--spoof', metavar='spoof', nargs='?', default='', help="The address to spoof (ip:host). If not specified the metric will not be spoofed.")
    parser.add_argument('--stdin', action='store_true', help="Read metrics from stdin. in 'key|value|timestamp' format.")
    
    p = parser.parse_args()

    if p.stdin:
        lines = sys.stdin.read().split("\n")
        metrics = [l.split("|") for l in lines if l]
    elif p.name and p.value:
        metrics = [[p.name[0], p.value[0], '0000000']]
    else:
        sys.exit(1)

    g = Gmetric(p.host, p.port, p.protocol)
    for key, value, timestamp in metrics:
        if not p.type:
            metric_type = classify_type(value)
            if metric_type == None:
                sys.exit(2)
        else:
            metric_type = p.type
        print metric_type
        g.send(key, value, TYPE=metric_type, UNITS=p.units, SLOPE=p.slope, TMAX=p.tmax, DMAX=p.dmin, GROUP=p.group, SPOOF=p.spoof)
    sys.exit(0)
