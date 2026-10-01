'use strict';
// Search thumbnails show page images as whole multiples of their native pixel art.
// Reviewed files are stored already enlarged by an integer source scale, so the native
// size is recovered from the pixels, then scaled by the largest integer that fits.

var MAX_PIXELS = 4000000;

function gcd( a, b ) {
	while ( b ) {
		var rest = a % b;
		a = b;
		b = rest;
	}
	return a;
}

/** Side of the square solid blocks an RGBA image is made of (1 for native-resolution art). */
function blockSize( data, width, height ) {
	function same( a, b ) {
		// Optimizers may rewrite the colour of fully transparent pixels.
		return ( data[ a + 3 ] === 0 && data[ b + 3 ] === 0 ) || (
			data[ a ] === data[ b ] && data[ a + 1 ] === data[ b + 1 ] &&
			data[ a + 2 ] === data[ b + 2 ] && data[ a + 3 ] === data[ b + 3 ] );
	}
	var size = gcd( width, height ), x, y, run;
	for ( y = 0; y < height && size > 1; y++ ) {
		for ( run = 1, x = 1; x < width; x++ ) {
			if ( same( ( y * width + x ) * 4, ( y * width + x - 1 ) * 4 ) ) {
				run++;
			} else {
				size = gcd( size, run );
				run = 1;
			}
		}
	}
	for ( x = 0; x < width && size > 1; x++ ) {
		for ( run = 1, y = 1; y < height; y++ ) {
			if ( same( ( y * width + x ) * 4, ( ( y - 1 ) * width + x ) * 4 ) ) {
				run++;
			} else {
				size = gcd( size, run );
				run = 1;
			}
		}
	}
	return Math.max( size, 1 );
}

/** Largest integer multiple of the native size within the box, or null if it cannot fit at 1x. */
function fit( nativeWidth, nativeHeight, boxWidth, boxHeight ) {
	var scale = Math.floor( Math.min( boxWidth / nativeWidth, boxHeight / nativeHeight ) );
	return scale >= 1 ? { width: nativeWidth * scale, height: nativeHeight * scale } : null;
}

var natives = Object.create( null );

function nativeSize( url ) {
	if ( !natives[ url ] ) {
		natives[ url ] = new Promise( function ( resolve ) {
			var image = new Image();
			image.onload = function () {
				var width = image.naturalWidth, height = image.naturalHeight;
				if ( !width || !height || width * height > MAX_PIXELS ) {
					resolve( null );
					return;
				}
				try {
					var canvas = document.createElement( 'canvas' );
					canvas.width = width;
					canvas.height = height;
					var context = canvas.getContext( '2d' );
					context.drawImage( image, 0, 0 );
					var size = blockSize( context.getImageData( 0, 0, width, height ).data, width, height );
					resolve( { width: width / size, height: height / size } );
				} catch ( error ) {
					// A cross-origin file repository cannot be read; keep the CSS fallback.
					resolve( null );
				}
			};
			image.onerror = function () {
				resolve( null );
			};
			image.src = url;
		} );
	}
	return natives[ url ];
}

function backgroundUrl( element ) {
	var match = /url\(\s*["']?(.*?)["']?\s*\)/.exec( element.style.backgroundImage );
	return match ? match[ 1 ] : '';
}

// Vector's typeahead (Codex) paints thumbnails as a fixed-size background.
function sizeBackground( element ) {
	var url = backgroundUrl( element );
	if ( !url || element.getAttribute( 'data-mirklurk-pixel' ) === url ) {
		return;
	}
	element.setAttribute( 'data-mirklurk-pixel', url );
	nativeSize( url ).then( function ( native ) {
		var size = native && backgroundUrl( element ) === url &&
			fit( native.width, native.height, element.clientWidth, element.clientHeight );
		if ( size ) {
			element.style.backgroundSize = size.width + 'px ' + size.height + 'px';
		}
	} );
}

// Special:Search renders an <img> stretched over a fixed box.
function sizeImage( image ) {
	var url = image.currentSrc || image.src;
	if ( !url || image.getAttribute( 'data-mirklurk-pixel' ) === url ) {
		return;
	}
	image.setAttribute( 'data-mirklurk-pixel', url );
	var boxWidth = image.clientWidth, boxHeight = image.clientHeight;
	nativeSize( url ).then( function ( native ) {
		var size = native && fit( native.width, native.height, boxWidth, boxHeight );
		if ( size ) {
			image.style.setProperty( 'width', size.width + 'px', 'important' );
			image.style.setProperty( 'height', size.height + 'px', 'important' );
		}
	} );
}

function scan() {
	Array.prototype.forEach.call( document.querySelectorAll( '.cdx-thumbnail__image' ), sizeBackground );
	Array.prototype.forEach.call( document.querySelectorAll( '.searchResultImage-thumbnail img' ), sizeImage );
}

if ( typeof document !== 'undefined' && typeof MutationObserver !== 'undefined' ) {
	var pending = false;
	new MutationObserver( function () {
		if ( !pending ) {
			pending = true;
			requestAnimationFrame( function () {
				pending = false;
				scan();
			} );
		}
	} ).observe( document.documentElement, {
		childList: true, subtree: true, attributes: true, attributeFilter: [ 'style' ]
	} );
	scan();
}

module.exports = { blockSize: blockSize, fit: fit, nativeSize: nativeSize };
