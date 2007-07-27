#! /bin/sh
gzip -c --best /var/log/system.log > /tmp/random.dat
openssl rand -rand file:random.dat 0
rm random.dat
openssl req  -config "make_certificate.cfg" -keyout "webshell.pem" -newkey rsa:1024 -nodes -x509 -days 365 -out "webshell.pem"
