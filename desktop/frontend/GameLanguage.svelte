<script lang="ts">
  export let encoding='win1252';
</script>

<label>Game language
  <select bind:value={encoding}>
    <option value="win1252">English / French / German / Italian / Spanish</option>
    <option value="win1251">Russian / other Cyrillic languages</option>
    <option value="win1250">Polish / Czech / other Central European languages</option>
  </select>
</label>
