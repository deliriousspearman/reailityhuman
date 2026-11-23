#!/usr/bin/env bash
# The bundle's sections, checked (deploy/sections.sh): install.sh runs it from the bundle's own copy of
# the project, after it has checked the core against SHA256SUMS.
#
#   check-bundle.sh <bundle> <stamp folder>
#
# Each section the bundle has is checked against its sums file (sums/<tag>.sha256, from its release),
# once: a stamp in <stamp folder> keeps that until the sums file changes. Then each section is listed:
# there and as the core expects (its SECTIONS file), there but a different release, there without a sums
# file (made separately, so not checked), or not there. Only a damaged section fails: a missing or
# different one is for the install's own checks, which leave out what needs it. Prints one line per
# section, "ok|warn|info|fail <text>", for install.sh to show; exits 1 if a section is damaged.
set -euo pipefail

bundle=${1:?usage: check-bundle.sh <bundle> <stamp folder>}
stamps=${2:?usage: check-bundle.sh <bundle> <stamp folder>}
# shellcheck source=deploy/sections.sh
source "$(dirname "${BASH_SOURCE[0]}")/sections.sh"
mkdir -p "$stamps"
bad=0

# Each sums file: its files there and unchanged.
shopt -s nullglob
for sums in "$bundle"/sums/*.sha256; do
	tag=$(basename "$sums" .sha256)
	stamp=$stamps/$tag
	if [[ -f $stamp && $(cat "$stamp") == "$(sha256sum <"$sums")" ]]; then
		continue
	fi
	if out=$(cd "$bundle" && sha256sum -c --quiet "$sums" 2>&1); then
		sha256sum <"$sums" >"$stamp"
	else
		n=$(grep -c ': FAILED' <<<"$out" || true)
		echo "fail $tag: $n file(s) missing or different from sums/$tag.sha256 (unpack every part of its release again): $(head -3 <<<"$out" | tr '\n' ';')"
		bad=1
	fi
done

# What the core was made with: "<section> <tag>" ("-" for office and isos: any will do).
expected=()
if [[ -f $bundle/SECTIONS ]]; then
	while read -r s t; do [[ $s == commit || -z $s ]] || expected+=("$s=$t"); done <"$bundle/SECTIONS"
fi
for e in "${expected[@]}"; do
	s=${e%%=*} want=${e#*=}
	[[ $s == core ]] && continue
	have=()
	for f in "$bundle"/sums/"$s"-*.sha256; do have+=("$(basename "$f" .sha256)"); done
	if ((${#have[@]} > 1)); then
		echo "warn $s: several releases of it unpacked (${have[*]}): their files are mixed; unpack just one into a fresh bundle"
	elif ((${#have[@]} == 1)); then
		if [[ $want == - || $want == "${have[0]}" ]]; then
			echo "ok $s: ${have[0]} ($(grep -c . "$bundle/sums/${have[0]}.sha256") files)"
		else
			echo "warn $s: ${have[0]}, but this core was made with $want: what changed between them shows as not ready in the checks below (release $want has it)"
		fi
	elif section_has "$bundle" "$s"; then
		echo "info $s: there, but without a sums file (made separately?), so not checked"
	else
		case $s in
			office) echo "info office: not in the bundle, so no Outlook (an office-* release, or media/windows/office/README.txt)" ;;
			isos) echo "info isos: no installer ISOs in the bundle (DOWNLOAD-LATER.md lists them)" ;;
			*) echo "info $s: not in the bundle (release $want, or DOWNLOAD-LATER.md says how to make it)" ;;
		esac
	fi
done
exit "$bad"
