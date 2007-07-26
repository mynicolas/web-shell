--------------------------------------------------------------------
WebShell
(C) 2007 by Marc S. Ressl
Released under the GPL 2.0
http://www-personal.umich.edu/~mressl/webshell

--------------------------------------------------------------------
WebShell is a web-based ssh shell.

It runs on any browser capable of JavaScript and AJAX. You can use
it from any computer or iPhone/smartphone.

The server is written in Python and is very easy to set up on Linux,
Mac OS X, *BSD, Solaris, and any Unix that runs python 2.3.

WebShell is based on Ajaxterm.

If you have any questions, use the forum on the website.

--------------------------------------------------------------------
Features

VT100, ECMA-48 terminal emulation
Integrated secure http server
UTF-8, with chinese/japanese wide glyph support
Virtual keyboard for iPhone users
Changeable appearance
Compliant with vttest

Planned Features

VT52 terminal emulation

Security

WebShell communications are as secure as a regular secure shell, as
both ssh and WebShell are on top of the SSL/TLS layer.

The code has been tested against buffer overflow and denial of
service. If you find any problem, please report it on the webpage.

--------------------------------------------------------------------
Installation

It is very easy to set up WebShell.

First, you need to make sure python 2.3 or later and OpenSSL are
installed on your system. You will also have to install the
pyOpenSSL python extensions to OpenSSL.

Next, you need to generate a server certificate. From the WebShell
directory enter these commands to quickly generate a certificate:

    export RANDFILE=/dev/random
    openssl req $@ -new -x509 -days 365 -nodes -out webshell.pem \
	-keyout webshell.pem

Now issue this command to run the server:

    ./webshell.py

To make sure that everything went well, go to this URL in your
browser:

    https://127.0.0.1:8022

Voila, enjoy WebShell.

--------------------------------------------------------------------
Thanks

Special thanks to Nicholas Jitkoff (the author of Quicksilver), for
helping to debug the user interface.

