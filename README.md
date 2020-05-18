# cimg
**A little utility for working with cockpits bots images**

cimg is a tiny little utility to make it easier to work with the images from the [cockpit bots](https://github.com/cockpit-project/bots/).

Its primary aims are:

 * modern commandline tool: git-style subcommands, tab completion and colour
 * capable of manipulating images without a cockpit checkout
 * installed as a normal command (ie: in `$PATH`)

It's currently very preliminary.

### Setting up

Clone the repository and run the `./install.sh` script.  That should
install things into the normal locations in your home directory.

You will need to run `cimg init` the first time.

### Using

So far, only the following commands are supported:

 * `init`: initial setup
 * `update`: update the bots repository
 * `status`: show the status of images
 * `download`: download images

### Examples

Show the summary status of all images:

```
cimg status
```

Show detailed status of a particular image:

```
cimg status debian-stable
```

Download one or more images (as needed):

```
cimg download fedora-3? debian*
```
