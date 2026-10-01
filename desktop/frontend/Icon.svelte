<script lang="ts">
  export let name:string;
  export let size=22;
  const paths:Record<string,string[]>={
    play:['M8 4.5 20 12 8 19.5Z'],
    stop:['M6 6h12v12H6z'],
    restart:['M20 7v5h-5','M20 12a8 8 0 1 0-2.3 5.7','M20 7l-2.3-2.3'],
    atlas:['m3 5 6-2 6 3 6-2v15l-6 2-6-3-6 2Z','M9 3v15M15 6v15'],
    recordings:['M4 3h16v18H4z','M8 3v18M16 3v18M4 7h4M4 12h4M4 17h4M16 7h4M16 12h4M16 17h4'],
    settings:['m9.5 3-.6 2.2-2 .9-2-.9-2.5 4.3 1.8 1.4v2.2L2.4 14.5 4.9 19l2-.9 2 .9.6 2h5l.6-2 2-.9 2 .9 2.5-4.5-1.8-1.4v-2.2l1.8-1.4L19.1 5l-2 .9-2-.9-.6-2Z'],
    diagnostics:['M2 12h4l3-9 5 18 3-9h5'],
    setup:['M14.7 6.3 18 3a6 6 0 0 0-7.6 7.6l-7 7a2.8 2.8 0 0 0 4 4l7-7A6 6 0 0 0 22 7l-3.3 3.3Z'],
    monitor:['M3 4h18v13H3z','M8 21h8M12 17v4'],
    cursor:['m5 3 14 10-7 1-4 7Z'],
    control:['M7 6h10c2 0 3 1.4 3.5 3.5l1 7c.4 3-2.1 3.6-3.5 1.5l-2-3H8l-2 3c-1.4 2.1-3.9 1.5-3.5-1.5l1-7C4 7.4 5 6 7 6Z','M6 10h4M8 8v4M16 9h.01M18 12h.01'],
    volume:['m11 4-5 4H3v8h3l5 4Z','M15 8a6 6 0 0 1 0 8M18 5a10 10 0 0 1 0 14'],
    mute:['m11 4-5 4H3v8h3l5 4Z','m16 9 6 6M22 9l-6 6'],
    disconnect:['m3 3 18 18','M10 5c5-1 9 2 12 7a18 18 0 0 1-4 4','M6 6a20 20 0 0 0-4 6c3 5 8 8 13 6'],
    export:['M12 16V3m-4 4 4-4 4 4','M7 10H4v11h16V10h-3'],
    folder:['M3 6h7l2 2h9v12H3Z','M3 6V4h6l2 2'],
    lock:['M5 11h14v10H5z','M8 11V7a4 4 0 0 1 8 0v4'],
    arrow:['M4 12h16m-6-6 6 6-6 6'],
  };
</script>

<svg class="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
  {#if name==='record'}<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/>
  {:else}{#each paths[name]??paths.monitor as d}<path {d}/>{/each}{/if}
  {#if name==='settings'}<circle cx="12" cy="12" r="3"/>{/if}
</svg>
