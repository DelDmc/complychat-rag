'''Per-client rate limits for POST /api/send-message/.

The endpoint needs no login, and every question it answers is paid for with
the deployment's OpenAI key. Fixing the model and the prompt on the server
caps what one call can cost; these limits cap how many calls one client gets.

Clients are told apart by IP address, which takes two decisions:

Which address. Behind Fly's proxy, REMOTE_ADDR is the proxy itself, the same
for every caller, and X-Forwarded-For is a list the caller can prepend to.
Fly sets Fly-Client-IP on every request to the address it accepted the
connection from, so that is the one to trust — but only on Fly. Anywhere else
the caller could send the header themselves, so it is read only when
settings.CLIENT_IP_HEADER names it, which fly.toml does.

How much of it. An IPv4 address is one client. An IPv6 client is routinely
handed a whole /64, and could otherwise walk through 2^64 addresses with a
fresh limit on each, so IPv6 is limited per /64.
'''

import ipaddress

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


def client_ip(request):
    '''The caller's address, as the trusted proxy saw it.'''
    header = settings.CLIENT_IP_HEADER
    if header:
        forwarded = request.META.get(header, '').strip()
        if forwarded:
            return forwarded
    return request.META.get('REMOTE_ADDR', '')


def rate_limit_key(ip):
    '''The unit one limit applies to: an IPv4 address, or an IPv6 /64.'''
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if address.version == 6:
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ipaddress.ip_network((address, 64), strict=False))
    return str(address)


class ClientRateThrottle(SimpleRateThrottle):
    '''Counts every caller by address, whether or not it authenticated.'''

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': rate_limit_key(client_ip(request)),
        }


class SendMessageBurstThrottle(ClientRateThrottle):
    scope = 'send_message_burst'


class SendMessageDailyThrottle(ClientRateThrottle):
    scope = 'send_message_daily'
